# --- START OF FILE server/app.py ---

from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from pymongo import MongoClient
from functools import wraps
from dotenv import load_dotenv
import os, datetime, math, requests, re
from bson.objectid import ObjectId
from googleapiclient.discovery import build

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
links_collection = db["links"]
settings_collection = db["settings"]
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

def extract_google_drive_file_id(url):
    pattern = r"drive\.google\.com/(?:file/d/|open\?id=)([a-zA-Z0-9_-]+)"; match = re.search(pattern, url); return match.group(1) if match else None
def format_size(size_bytes):
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes <= 0: return "Unknown"
    size_name = ("B", "KB", "MB", "GB", "TB"); i = int(math.floor(math.log(size_bytes, 1024))); p = math.pow(1024, i); s = round(size_bytes / p, 2); return f"{s} {size_name[i]}"
@app.context_processor
def utility_processor(): return dict(format_size=format_size)

# ... (Auth and other simple routes remain the same) ...
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session: return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username, password = request.form.get("username"), request.form.get("password")
        if username == os.getenv("USERNAME") and password == os.getenv("PASSWORD"): session["logged_in"] = True; return redirect(url_for("dashboard"))
        else: return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")
@app.route("/logout")
def logout(): session.pop("logged_in", None); return redirect(url_for("login"))
@app.route("/")
def home(): return redirect(url_for("login"))
@app.route("/dashboard")
@login_required
def dashboard(): all_links = list(links_collection.find().sort("added_at", -1)); return render_template("dashboard.html", links=all_links)
@app.route("/admin/ads", methods=["GET", "POST"])
@login_required
def manage_ads():
    if request.method == "POST":
        ads_doc = {"header_ad": request.form.get("header_ad"),"details_ad": request.form.get("details_ad"),"footer_ad": request.form.get("footer_ad")}
        settings_collection.update_one({}, {"$set": ads_doc}, upsert=True)
        return redirect(url_for("manage_ads"))
    current_ads = settings_collection.find_one() or {}
    return render_template("ads.html", ads=current_ads)
@app.route("/api/add_link", methods=["POST"])
def api_add_link():
    try:
        data = request.get_json(); url = data.get("url"); filename = data.get("filename")
        file_id = extract_google_drive_file_id(url); is_gdrive = bool(file_id)
        if not filename:
            try:
                if is_gdrive: service = build('drive', 'v3', developerKey=GOOGLE_API_KEY); filename = service.files().get(fileId=file_id, fields='name').execute().get('name')
                else:
                    with requests.head(url, allow_redirects=True, timeout=5) as h:
                        if 'content-disposition' in h.headers: filename = re.search(r'filename="?([^"]+)"?', h.headers['content-disposition']).group(1)
            except Exception: filename = url.split('/')[-1] or "File"
        link_doc = {"original_url": url, "filename": filename, "is_gdrive": is_gdrive, "file_id": file_id, "added_at": datetime.datetime.utcnow()}
        links_collection.insert_one(link_doc)
        return jsonify({"status": "success", "link": {"_id": str(link_doc['_id']), "filename": filename}})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500
@app.route("/delete/<link_id>", methods=["POST"])
@login_required
def delete_link(link_id):
    links_collection.delete_one({"_id": ObjectId(link_id)}); return redirect(url_for("dashboard"))

# <<< THE FINAL AND MOST RELIABLE DOWNLOAD PAGE ROUTE >>>
@app.route("/download/<link_id>")
def download_page(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info: return "❌ লিঙ্কটি খুঁজে পাওয়া যায়নি।", 404
        
        ads = settings_collection.find_one() or {}
        
        # --- Prepare the final download link right here ---
        if link_info.get("is_gdrive"):
            file_id = link_info['file_id']
            final_download_link = f"https://drive.google.com/uc?export=download&id={file_id}"
        else:
            final_download_link = link_info['original_url']

        # --- Fetch file size for display ---
        file_size = None
        try:
            if link_info.get("is_gdrive") and GOOGLE_API_KEY:
                service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
                file_size = int(service.files().get(fileId=link_info['file_id'], fields='size').execute().get('size', 0))
            else:
                with requests.head(link_info['original_url'], allow_redirects=True, timeout=5) as h:
                    if h.status_code == 200 and 'content-length' in h.headers:
                        file_size = int(h.headers['content-length'])
        except Exception:
            pass
        
        link_info['size'] = file_size
        
        # --- Pass the final link to the template ---
        return render_template("file.html", link_info=link_info, ads=ads, final_download_link=final_download_link)
        
    except Exception as e:
        return f"An error occurred: {e}", 500

# The /direct/<link_id> route is no longer needed and has been removed.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

# --- END OF FILE server/app.py ---
