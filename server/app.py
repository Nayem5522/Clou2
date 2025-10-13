# server/app.py

import os, datetime, math, asyncio, atexit
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_file, Response
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
from bson.objectid import ObjectId
from pyrogram import Client
from io import BytesIO

load_dotenv()

# --- Flask App এবং Pyrogram ক্লায়েন্ট শুরু করা ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Pyrogram ক্লায়েন্ট (বটের টোকেন দিয়ে লগইন করা হচ্ছে)
pyro_bot = Client(
    "web_session",
    api_id=int(os.getenv("API_ID")),
    api_hash=os.getenv("API_HASH"),
    bot_token=os.getenv("BOT_TOKEN")
)

# MongoDB ক্লায়েন্ট
client = MongoClient(os.getenv("MONGO_URI"))
db = client["r2s_bot"]
files_collection = db["files"]

# --- ফাইল সাইজ ফরম্যাট করার ফাংশন ---
def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

@app.context_processor
def utility_processor():
    return dict(format_size=format_size)

# --- Auth Decorator ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# --- Routes ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == os.getenv("USERNAME") and request.form.get("password") == os.getenv("PASSWORD"):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
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
@login_required
async def api_upload():
    try:
        f = request.files.get("file")
        if not f:
            return jsonify({"status": "error", "message": "No file found"}), 400

        filename = secure_filename(f.filename)
        file_size = request.content_length
        
        # ফাইলটি টেলিগ্রাম চ্যানেলে পাঠানো হচ্ছে
        sent_message = await pyro_bot.send_document(
            chat_id=int(os.getenv("STORAGE_CHANNEL_ID")),
            document=f,
            file_name=filename
        )

        # ডাটাবেসে তথ্য সংরক্ষণ
        file_doc = {
            "filename": filename,
            "size": file_size,
            "message_id": sent_message.id,
            "uploaded_at": datetime.datetime.utcnow(),
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
        return render_template("file.html", file_info=file_info, file_id=file_id) if file_info else ("❌ File not found", 404)
    except:
        return "❌ Invalid file ID", 404

@app.route("/direct/<file_id>")
async def direct_download(file_id):
    try:
        file_info = files_collection.find_one({"_id": ObjectId(file_id)})
        if not file_info:
            return "❌ File not found", 404

        # টেলিগ্রাম থেকে ফাইল স্ট্রিম করা হচ্ছে
        async def generate():
            async for chunk in pyro_bot.stream_media(
                chat_id=int(os.getenv("STORAGE_CHANNEL_ID")),
                message_id=file_info['message_id']
            ):
                yield chunk

        return Response(generate(), headers={
            'Content-Disposition': f'attachment; filename="{file_info["filename"]}"'
        })
    except Exception as e:
        return "❌ Download failed", 500

@app.route("/delete/<file_id>", methods=["POST"])
@login_required
async def delete_file(file_id):
    try:
        file_info = files_collection.find_one_and_delete({"_id": ObjectId(file_id)})
        if file_info:
            await pyro_bot.delete_messages(
                chat_id=int(os.getenv("STORAGE_CHANNEL_ID")),
                message_ids=file_info['message_id']
            )
        return redirect(url_for("dashboard"))
    except:
        return "Delete failed", 500
        
@app.route("/")
def home():
    return redirect(url_for("login"))

async def main():
    await pyro_bot.start()
    # Flask app টি Gunicorn দিয়ে চালানো হবে, তাই এখানে app.run() নেই

if __name__ == '__main__':
    # এই অংশটি শুধুমাত্র লোকাল টেস্টিং এর জন্য
    loop = asyncio.get_event_loop()
    loop.run_until_complete(pyro_bot.start())
    app.run(host="0.0.0.0", port=10000)
    loop.run_until_complete(pyro_bot.stop())
else:
    # Render-এ ডেপ্লয় করার জন্য
    asyncio.get_event_loop().run_until_complete(main())

