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
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key_for_clou2")

# --- Database Connection ---
client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
links_collection = db["links"]
settings_collection = db["settings"]
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# --- Helper Functions ---
def extract_google_drive_file_id(url):
    pattern = r"drive\.google\.com/(?:file/d/|open\?id=)([a-zA-Z0-9_-]+)"; match = re.search(pattern, url); return match.group(1) if match else None
def format_size(size_bytes):
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes <= 0: return "Unknown"
    size_name = ("B", "KB", "MB", "GB", "TB"); i = int(math.floor(math.log(size_bytes, 1024))); p = math.pow(1024, i); s = round(size_bytes / p, 2); return f"{s} {size_name[i]}"
@app.context_processor
def utility_processor(): return dict(format_size=format_size)

# --- Authentication ---
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
    if "logged_in" in session: return redirect(url_for("dashboard"))
    return render_template("login.html")
@app.route("/logout")
def logout(): session.pop("logged_in", None); return redirect(url_for("login"))
@app.route("/")
def home(): return redirect(url_for("login"))

# --- Main Dashboard ---
@app.route("/dashboard")
@login_required
def dashboard():
    # Fetch only active links (where deleted_at does not exist)
    active_links = list(links_collection.find({"deleted_at": {"$exists": False}}).sort("added_at", -1))
    # Fetch only soft-deleted links (where deleted_at exists)
    deleted_links = list(links_collection.find({"deleted_at": {"$exists": True}}).sort("deleted_at", -1))
    return render_template("dashboard.html", active_links=active_links, deleted_links=deleted_links)

# --- Link Management ---
@app.route("/api/add_link", methods=["POST"])
def api_add_link():
    if "logged_in" not in session: return jsonify({"status": "error", "message": "Authentication required"}), 401
    try:
        data = request.get_json(); url = data.get("url"); filename = data.get("filename")
        if not url: return jsonify({"status": "error", "message": "URL is required"}), 400
        
        file_id = extract_google_drive_file_id(url); is_gdrive = bool(file_id)
        if not filename:
            try:
                if is_gdrive and GOOGLE_API_KEY: 
                    service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
                    filename = service.files().get(fileId=file_id, fields='name').execute().get('name')
                else:
                    with requests.head(url, allow_redirects=True, timeout=5) as h:
                        if 'content-disposition' in h.headers: 
                            filename = re.search(r'filename="?([^"]+)"?', h.headers['content-disposition']).group(1)
                        else:
                            filename = url.split('/')[-1].split('?')[0] or "File"
            except Exception: filename = url.split('/')[-1].split('?')[0] or "File"

        link_doc = {"original_url": url, "filename": filename, "is_gdrive": is_gdrive, "file_id": file_id, "added_at": datetime.datetime.utcnow()}
        result = links_collection.insert_one(link_doc)
        
        # Prepare data for JSON response, converting ObjectId to string
        link_doc['_id'] = str(result.inserted_id)
        link_doc['added_at'] = link_doc['added_at'].isoformat()

        return jsonify({"status": "success", "link": link_doc})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/delete/<link_id>", methods=["POST"])
@login_required
def delete_link(link_id):
    # Soft delete: set a 'deleted_at' timestamp instead of removing
    links_collection.update_one(
        {"_id": ObjectId(link_id)},
        {"$set": {"deleted_at": datetime.datetime.utcnow()}}
    )
    return redirect(url_for("dashboard"))

@app.route("/restore/<link_id>", methods=["POST"])
@login_required
def restore_link(link_id):
    # Restore: remove the 'deleted_at' field
    links_collection.update_one(
        {"_id": ObjectId(link_id)},
        {"$unset": {"deleted_at": ""}}
    )
    return redirect(url_for("dashboard"))

@app.route("/force-delete/<link_id>", methods=["POST"])
@login_required
def force_delete_link(link_id):
    # Permanent delete
    links_collection.delete_one({"_id": ObjectId(link_id)})
    return redirect(url_for("dashboard"))
    
# --- Ads Management ---
@app.route("/admin/ads", methods=["GET", "POST"])
@login_required
def manage_ads():
    if request.method == "POST":
        ads_doc = {"header_ad": request.form.get("header_ad"),"details_ad": request.form.get("details_ad"),"footer_ad": request.form.get("footer_ad")}
        settings_collection.update_one({}, {"$set": ads_doc}, upsert=True)
        return redirect(url_for("manage_ads"))
    current_ads = settings_collection.find_one() or {}
    return render_template("ads.html", ads=current_ads)

# --- Public Download Page --- 

# --- START OF SIMPLIFIED app.py FUNCTION ---

@app.route("/download/<link_id>")
def download_page(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        # লিঙ্কটি মুছে ফেলা হয়েছে কিনা তা পরীক্ষা করুন
        if not link_info or 'deleted_at' in link_info:
            return "❌ Link not found or has been deleted.", 404
        
        ads = settings_collection.find_one() or {}
        
        # আমরা এখন শুধু একটি সাধারণ ডাউনলোড লিঙ্ক তৈরি করব
        # বাকি কাজ ফ্রন্টএন্ডের জাভাস্ক্রিপ্ট করবে
        if link_info.get("is_gdrive"):
            final_download_link = f"https://drive.google.com/uc?export=download&id={link_info['file_id']}"
        else:
            final_download_link = link_info['original_url']

        file_size = None
        try:
            if link_info.get("is_gdrive") and GOOGLE_API_KEY:
                service = build('drive', 'v3', developerKey=GOOGLE_API_KEY)
                file_size = int(service.files().get(fileId=link_info['file_id'], fields='size').execute().get('size', 0))
            else:
                # অপ্রয়োজনীয় হেড রিকোয়েস্ট এড়ানোর জন্য এই অংশ বাদ দেওয়া যেতে পারে যদি পারফর্মেন্স ইস্যু হয়
                with requests.head(link_info['original_url'], allow_redirects=True, timeout=5) as h:
                    if h.status_code == 200 and 'content-length' in h.headers:
                        file_size = int(h.headers['content-length'])
        except Exception: pass
        
        link_info['size'] = file_size
        
        return render_template("file.html", link_info=link_info, ads=ads, final_download_link=final_download_link, current_year=datetime.datetime.now().year)
        
    except Exception as e:
        return f"An error occurred: {e}", 500

# --- END OF SIMPLIFIED app.py FUNCTION ---



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))

# --- END OF FILE server/app.py ---
