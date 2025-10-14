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

def convert_google_drive_url(url):
    pattern = r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def format_size(size_bytes):
    if size_bytes == 0 or not isinstance(size_bytes, (int, float)):
        return "Unknown"
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
    all_links = list(links_collection.find().sort("added_at", -1))
    return render_template("dashboard.html", links=all_links)

@app.route("/api/add_link", methods=["POST"])
def api_add_link():
    try:
        data = request.get_json()
        original_url = data.get("url")
        filename = data.get("filename")

        if not original_url:
            return jsonify({"status": "error", "message": "URL is required"}), 400
        
        processed_url = convert_google_drive_url(original_url)

        if not filename:
            try:
                # We need a session to handle cookies for large file name detection
                with requests.Session() as s:
                    head_req = s.get(processed_url, stream=True, timeout=10)
                    confirm_token_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', head_req.text)
                    if confirm_token_match:
                        params = {'confirm': confirm_token_match.group(1)}
                        head_req = s.get(processed_url, params=params, stream=True, timeout=10)

                    if head_req.status_code == 200 and 'content-disposition' in head_req.headers:
                        cd = head_req.headers['content-disposition']
                        filename = re.search(r'filename="?([^"]+)"?', cd).group(1)
                    else:
                        filename = "file_name_not_found"
            except requests.RequestException:
                filename = "file_name_not_found"

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
                "filename": filename,
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
        
        file_size = 0
        try:
            head_req = requests.head(link_info['original_url'], allow_redirects=True, timeout=5)
            if head_req.status_code == 200 and 'content-length' in head_req.headers:
                file_size = int(head_req.headers['content-length'])
        except requests.RequestException:
            pass

        link_info['size'] = file_size
        return render_template("file.html", link_info=link_info, link_id=link_id)
        
    except Exception:
        return "❌ অবৈধ লিঙ্ক আইডি।", 404

# <<< MODIFIED FUNCTION TO HANDLE LARGE GOOGLE DRIVE FILES >>>
@app.route("/direct/<link_id>")
def direct_download(link_id):
    try:
        link_info = links_collection.find_one({"_id": ObjectId(link_id)})
        if not link_info:
            return "❌ এই লিঙ্কের কোনো তথ্য পাওয়া যায়নি।", 404
        
        original_url = link_info.get("original_url")
        
        # কুকি সেশন ম্যানেজ করার জন্য একটি সেশন অবজেক্ট তৈরি করা
        session = requests.Session()

        # প্রথম রিকোয়েস্ট ( কুকি এবং কনফার্মেশন টোকেন পাওয়ার জন্য )
        req = session.get(original_url, stream=True, allow_redirects=True, timeout=10)
        
        # কনফার্মেশন টোকেন খোঁজা
        confirm_token_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', req.text)
        
        # যদি টোকেন পাওয়া যায় (অর্থাৎ, এটি একটি বড় ফাইল), তবে টোকেন সহ দ্বিতীয় রিকোয়েস্ট পাঠানো
        if confirm_token_match:
            params = {'confirm': confirm_token_match.group(1)}
            req = session.get(original_url, params=params, stream=True, allow_redirects=True, timeout=10)

        # এখন `req` অবজেক্টে আসল ফাইল ডেটা থাকা উচিত
        if req.status_code != 200:
            error_map = {
                404: "মূল লিঙ্ক থেকে ফাইলটি খুঁজে পাওয়া যায়নি (Error 404)।",
                403: "এই ফাইলটি ডাউনলোড করার অনুমতি নেই (Error 403)।",
            }
            return error_map.get(req.status_code, f"মূল সার্ভারে একটি সমস্যা হয়েছে (Error {req.status_code})।"), req.status_code

        content_type = req.headers.get('content-type', '')
        if 'text/html' in content_type:
            return "❌ প্রদত্ত লিঙ্কটি সরাসরি ডাউনলোড লিঙ্ক নয় অথবা কোনো সমস্যা হয়েছে।", 400

        headers = {
            'Content-Disposition': f'attachment; filename="{link_info["filename"]}"',
            'Content-Type': content_type,
            'Content-Length': req.headers.get('content-length'),
        }

        return Response(stream_with_context(req.iter_content(chunk_size=8192)), headers=headers)

    except requests.exceptions.RequestException as e:
        return f"❌ মূল লিঙ্কের সাথে সংযোগ স্থাপন করা যাচ্ছে না। Error: {e}", 500
    except Exception as e:
        return f"❌ একটি অপ্রত্যাশিত সমস্যা হয়েছে: {str(e)}", 500


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
