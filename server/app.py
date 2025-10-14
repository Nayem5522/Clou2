# --- START OF FILE server/app.py ---

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, Response, stream_with_context
from pymongo import MongoClient
from functools import wraps
from dotenv import load_dotenv
import os, datetime, math, requests, re
from bson.objectid import ObjectId

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
links_collection = db["links"]

# <<< FINAL FIX: Add a browser-like User-Agent Header >>>
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def convert_google_drive_url(url):
    pattern = r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

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

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ... (login and logout routes remain unchanged) ...
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


# <<< SIMPLIFIED & MORE RELIABLE /api/add_link >>>
@app.route("/api/add_link", methods=["POST"])
def api_add_link():
    try:
        data = request.get_json()
        original_url = data.get("url")
        filename = data.get("filename")

        if not original_url:
            return jsonify({"status": "error", "message": "URL is required"}), 400
        
        processed_url = convert_google_drive_url(original_url)

        # Do not try to get filename here. It is slow and unreliable.
        # Use user-provided name or a generic one.
        if not filename:
            filename = "Google Drive File" # A better placeholder

        link_doc = {
            "original_url": processed_url,
            "filename": filename,
            "added_at": datetime.datetime.utcnow(),
        }
        result = links_collection.insert_one(link_doc)

        return jsonify({
            "status": "success",
            "link": {
                "_id": str(result.inserted_id),
                "filename": filename, # Return the name we used
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/download/<link_id>")
def download_page(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info:
            return "❌ লিঙ্কটি খুঁজে পাওয়া যায়নি।", 404
        
        # We can still try to get the size here for display purposes
        file_size = None
        try:
            # Use HEAD request for efficiency
            with requests.head(link_info['original_url'], headers=HEADERS, allow_redirects=True, timeout=5) as head_req:
                if head_req.status_code == 200 and 'content-length' in head_req.headers:
                    file_size = int(head_req.headers['content-length'])
        except requests.RequestException:
            pass # It's okay if we can't get the size

        link_info['size'] = file_size
        return render_template("file.html", link_info=link_info, link_id=link_id)
        
    except Exception:
        return "❌ অবৈধ লিঙ্ক আইডি।", 404

# <<< FULLY REVISED /direct/<link_id> with User-Agent >>>
@app.route("/direct/<link_id>")
def direct_download(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info:
            return "❌ এই লিঙ্কের কোনো তথ্য পাওয়া যায়নি।", 404
        
        original_url = link_info.get("original_url")
        
        session = requests.Session()
        session.headers.update(HEADERS) # Add headers to the entire session

        # First request to get cookies and confirmation token
        req = session.get(original_url, stream=True, allow_redirects=True, timeout=15)
        
        confirm_token_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', req.text)
        
        if confirm_token_match:
            params = {'confirm': confirm_token_match.group(1)}
            req = session.get(original_url, params=params, stream=True, allow_redirects=True, timeout=15)

        if req.status_code != 200:
            return f"মূল সার্ভারে একটি সমস্যা হয়েছে (Error {req.status_code})।", req.status_code

        content_type = req.headers.get('content-type', '')
        if 'text/html' in content_type:
            # If we still get HTML, it's a definitive failure
            return "❌ গুগল ড্রাইভ এই ফাইলটি ডাউনলোড করার অনুমতি দিচ্ছে না। এটি ব্যক্তিগত (private) হতে পারে অথবা ডাউনলোডের সীমা অতিক্রম করেছে।", 403

        # Try to get the real filename from the final response header
        final_filename = link_info["filename"]
        if 'content-disposition' in req.headers:
            cd = req.headers['content-disposition']
            fn_match = re.search(r'filename="?([^"]+)"?', cd)
            if fn_match:
                final_filename = fn_match.group(1)

        headers = {
            'Content-Disposition': f'attachment; filename="{final_filename}"',
            'Content-Type': content_type,
            'Content-Length': req.headers.get('content-length'),
        }

        return Response(stream_with_context(req.iter_content(chunk_size=8192)), headers=headers)

    except requests.exceptions.RequestException as e:
        return f"❌ মূল লিঙ্কের সাথে সংযোগ স্থাপন করা যাচ্ছে না। Error: {e}", 500
    except Exception as e:
        return f"❌ একটি অপ্রত্যাশিত সমস্যা হয়েছে: {str(e)}", 500

# ... (delete and home routes remain unchanged) ...
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
