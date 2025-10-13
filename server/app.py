from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
import os, datetime

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
files_collection = db["files"]

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Auth decorator ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# --- Login route ---
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

# --- Dashboard ---
@app.route("/dashboard")
@login_required
def dashboard():
    all_files = list(files_collection.find().sort("uploaded_at", -1))
    return render_template("dashboard.html", files=all_files)

# --- API Upload ---
@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file found in request."})

        f = request.files["file"]
        filename = secure_filename(f.filename)
        path = os.path.join(UPLOAD_FOLDER, filename)
        f.save(path)

        file_doc = {
            "filename": filename,
            "uploaded_at": datetime.datetime.utcnow(),
            "size": os.path.getsize(path),
        }
        files_collection.insert_one(file_doc)

        return jsonify({
            "status": "success",
            "download_url": f"{os.getenv('BASE_URL')}/download/{filename}"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- Download page ---
@app.route("/download/<filename>")
def download(filename):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        return "❌ File not found", 404
    file_info = files_collection.find_one({"filename": filename})
    return render_template("file.html", filename=filename, size=file_info.get("size"))

@app.route("/direct/<filename>")
def direct_download(filename):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return "❌ File not found", 404

@app.route("/")
def home():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
  
