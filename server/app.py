from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
import os, datetime, math
from gridfs import GridFSBucket
from bson.objectid import ObjectId

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]

fs = GridFSBucket(db)
files_collection = db["files"]

def format_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

@app.context_processor
def utility_processor():
    return dict(format_size=format_size)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == os.getenv("USERNAME") and password == os.getenv("PASSWORD"):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    all_files = list(files_collection.find().sort("uploaded_at", -1))
    return render_template("dashboard.html", files=all_files)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file found"}), 400
        
        f = request.files["file"]
        filename = secure_filename(f.filename)
        file_size = request.content_length

        gridfs_id = fs.upload_from_stream(
            filename, f.stream, metadata={"contentType": f.mimetype}
        )
        
        file_doc = {
            "filename": filename,
            "uploaded_at": datetime.datetime.utcnow(),
            "size": file_size,
            "gridfs_id": gridfs_id
        }
        result = files_collection.insert_one(file_doc)

        return jsonify({
            "status": "success",
            "file": {
                "_id": str(result.inserted_id),
                "filename": filename,
                "size_formatted": format_size(file_size)
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/download/<file_id>")
def download(file_id):
    try:
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if file_info:
            return render_template("file.html", file_info=file_info, file_id=file_id)
        else:
            return "❌ File not found", 404
    except:
        return "❌ Invalid file ID", 404

@app.route("/direct/<file_id>")
def direct_download(file_id):
    try:
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if not file_info:
            return "❌ File not found in database", 404
        
        grid_out = fs.open_download_stream(file_info['gridfs_id'])
        
        return send_file(
            grid_out,
            mimetype=grid_out.metadata.get('contentType', 'application/octet-stream'),
            as_attachment=True,
            download_name=file_info['filename']
        )
    except Exception as e:
        return "❌ File not found or error occurred", 404

@app.route("/delete/<file_id>", methods=["POST"])
@login_required
def delete_file(file_id):
    try:
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if file_info:
            fs.delete(file_info['gridfs_id'])
            files_collection.delete_one({"_id": ObjectId(file_id)})
            return redirect(url_for("dashboard"))
        else:
            return "File not found", 404
    except Exception as e:
        return f"An error occurred: {str(e)}", 500

@app.route("/")
def home():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
