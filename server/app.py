# --- START OF FILE server/app.py ---

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, Response, stream_with_context
from pymongo import MongoClient
from functools import wraps
from dotenv import load_dotenv
import os, datetime, math, requests, re, io
from bson.objectid import ObjectId
# Google Drive API Imports
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.exceptions import DefaultCredentialsError

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

# --- Configurations ---
client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
links_collection = db["links"]
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- Helper Functions ---
def extract_google_drive_file_id(url):
    pattern = r"drive\.google\.com/(?:file/d/|open\?id=)([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    return match.group(1) if match else None

def format_size(size_bytes):
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes <= 0:
        return "Unknown"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

@app.context_processor
def utility_processor():
    return dict(format_size=format_size)

# ... (Authentication routes: login, logout, login_required remain unchanged) ...
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
    all_links = list(links_collection.find().sort("added_at", -1))
    return render_template("dashboard.html", links=all_links)

@app.route("/api/add_link", methods=["POST"])
def api_add_link():
    try:
        data = request.get_json()
        url = data.get("url")
        filename = data.get("filename")
        
        file_id = extract_google_drive_file_id(url)
        is_gdrive = bool(file_id)

        if not filename and is_gdrive:
            try:
                if not GOOGLE_API_KEY: raise ValueError("Google API Key not configured.")
                service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
                file_metadata = service.files().get(fileId=file_id, fields='name').execute()
                filename = file_metadata.get('name', 'Google Drive File')
            except (ValueError, DefaultCredentialsError) as e:
                 return jsonify({"status": "error", "message": str(e)}), 500
            except Exception:
                 filename = "Google Drive File" # Fallback
        elif not filename:
            filename = "Direct Link File"

        link_doc = {
            "original_url": url,
            "filename": filename,
            "is_gdrive": is_gdrive,
            "file_id": file_id,
            "added_at": datetime.datetime.utcnow(),
        }
        result = links_collection.insert_one(link_doc)
        return jsonify({"status": "success", "link": {"_id": str(result.inserted_id), "filename": filename}})
    except Exception as e:
        return jsonify({"status": "error", "message": f"An error occurred: {e}"}), 500

@app.route("/download/<link_id>")
def download_page(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info: return "❌ লিঙ্কটি খুঁজে পাওয়া যায়নি।", 404
        
        file_size = None
        try:
            if link_info.get("is_gdrive"):
                if not GOOGLE_API_KEY: raise ValueError("API Key not found")
                service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
                file_metadata = service.files().get(fileId=link_info['file_id'], fields='size').execute()
                file_size = int(file_metadata.get('size', 0))
            else:
                with requests.head(link_info['original_url'], allow_redirects=True, timeout=5) as head_req:
                    if head_req.status_code == 200 and 'content-length' in head_req.headers:
                        file_size = int(head_req.headers['content-length'])
        except Exception:
            pass # It's okay if size cannot be determined

        link_info['size'] = file_size
        return render_template("file.html", link_info=link_info, link_id=link_id)
    except Exception: return "❌ অবৈধ লিঙ্ক আইডি।", 404

@app.route("/direct/<link_id>")
def direct_download(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info: return "❌ এই লিঙ্কের কোনো তথ্য পাওয়া যায়নি।", 404
        
        # --- BRANCH 1: GOOGLE DRIVE API DOWNLOADER ---
        if link_info.get("is_gdrive"):
            if not GOOGLE_API_KEY: return "Google Drive API Key is not configured.", 500
            
            file_id = link_info['file_id']
            service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
            metadata = service.files().get(fileId=file_id, fields='name, size, mimeType').execute()
            filename = metadata.get('name')
            filesize = metadata.get('size')
            mimetype = metadata.get('mimeType')

            request_to_gdrive = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request_to_gdrive, chunksize=1024*1024)
            
            def generate_content():
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    fh.seek(0)
                    yield fh.read()
                    fh.seek(0)
                    fh.truncate()

            headers = {
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': filesize,
                'Content-Type': mimetype
            }
            return Response(stream_with_context(generate_content()), headers=headers)

        # --- BRANCH 2: REGULAR DIRECT LINK DOWNLOADER ---
        else:
            req = requests.get(link_info['original_url'], stream=True, allow_redirects=True, timeout=30)
            if req.status_code != 200: 
                return f"Error fetching from source server: Status {req.status_code}", 502

            headers = {
                'Content-Disposition': f'attachment; filename="{link_info["filename"]}"',
                'Content-Length': req.headers.get('content-length'),
                'Content-Type': req.headers.get('content-type', 'application/octet-stream')
            }
            return Response(stream_with_context(req.iter_content(chunk_size=8192)), headers=headers)

    except Exception as e:
        return f"❌ একটি অপ্রত্যাশিত সমস্যা হয়েছে: {e}", 500
        
# ... (Delete and home routes remain unchanged) ...
@app.route("/delete/<link_id>", methods=["POST"])
@login_required
def delete_link(link_id):
    try:
        result = links_collection.delete_one({"_id": ObjectId(link_id)})
        if result.deleted_count == 1:
            return redirect(url_for("dashboard"))
        else:
            return "লিঙ্কটি খুঁজে পাওয়া যায়নি।", 404
    except Exception as e:
        return f"একটি সমস্যা হয়েছে: {str(e)}", 500

@app.route("/")
def home():
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

# --- END OF FILE server/app.py ---
