# server/app.py

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
import os, datetime

# GridFS এবং ObjectId ব্যবহারের জন্য নতুন ইম্পোর্ট
from gridfs import GridFSBucket
from bson.objectid import ObjectId

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]

# GridFS bucket তৈরি করা হলো
fs = GridFSBucket(db)
files_collection = db["files"]

# UPLOAD_FOLDER আর প্রয়োজন নেই, কারণ ফাইল এখন ডাটাবেসে সেভ হবে
# UPLOAD_FOLDER = "uploads"
# os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

# --- API Upload (GridFS দিয়ে আপডেট করা) ---
@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file found in request."})

        f = request.files["file"]
        filename = secure_filename(f.filename)

        # ফাইলটি সরাসরি GridFS-এ আপলোড করা হচ্ছে
        # f.stream ব্যবহার করে ফাইল কন্টেন্ট পড়া হচ্ছে
        gridfs_id = fs.upload_from_stream(filename, f.stream, metadata={"contentType": f.mimetype})
        
        # ডাটাবেসে ফাইলের তথ্য সেভ করা হচ্ছে
        file_doc = {
            "filename": filename,
            "uploaded_at": datetime.datetime.utcnow(),
            "size": f.content_length, # ফাইলের সাইজ রিকোয়েস্ট থেকে নেওয়া হচ্ছে
            "gridfs_id": gridfs_id  # GridFS থেকে পাওয়া ID সেভ করা হচ্ছে
        }
        result = files_collection.insert_one(file_doc)

        # ডাউনলোড URL-এ ফাইলের নামের পরিবর্তে ডাটাবেসের ইউনিক ID ব্যবহার করা হচ্ছে
        return jsonify({
            "status": "success",
            "download_url": f"{os.getenv('BASE_URL')}/download/{str(result.inserted_id)}"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- Download page (ID দিয়ে আপডেট করা) ---
@app.route("/download/<file_id>")
def download(file_id):
    try:
        # স্ট্রিং ID-কে ObjectId-তে কনভার্ট করে ফাইল খোঁজা হচ্ছে
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if file_info:
            return render_template("file.html", filename=file_info.get("filename"), size=file_info.get("size"), file_id=file_id)
        else:
            return "❌ File not found", 404
    except:
        return "❌ Invalid file ID", 404


# --- Direct Download (GridFS দিয়ে আপডেট করা) ---
@app.route("/direct/<file_id>")
def direct_download(file_id):
    try:
        # file_id দিয়ে ডাটাবেস থেকে ফাইলের তথ্য আনা হচ্ছে
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if not file_info:
            return "❌ File not found in database", 404
        
        # GridFS ID দিয়ে GridFS থেকে ফাইলটি স্ট্রীম হিসেবে খোলা হচ্ছে
        grid_out = fs.open_download_stream(file_info['gridfs_id'])

        # ফাইলটি send_file ব্যবহার করে ইউজারকে পাঠানো হচ্ছে
        return send_file(
            grid_out,
            mimetype=grid_out.metadata['contentType'],
            as_attachment=True,
            download_name=file_info['filename']
        )
    except Exception as e:
        return "❌ File not found or error occurred", 404


@app.route("/")
def home():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
