# bot/bot.py

import asyncio, os, datetime
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config import BOT_TOKEN, API_ID, API_HASH, BASE_URL, MONGO_URI, STORAGE_CHANNEL_ID
from bot.utils import progress_callback

# Pyrogram ক্লায়েন্ট
app = Client("r2s-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB ক্লায়েন্ট
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["r2s_bot"]
files_collection = db["files"]

# /start মেসেজ
@app.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    await message.reply_text(
        "👋 **Welcome!**\n\nI will upload your files to a secure channel and give you a permanent shareable link."
    )

# ফাইল হ্যান্ডলার
@app.on_message(filters.document | filters.video | filters.audio)
async def handle_file(client, message: Message):
    user_message = await message.reply_text("📥 Processing your file...", quote=True)
    
    try:
        # ফাইলটি স্টোরেজ চ্যানেলে ফরোয়ার্ড করা হচ্ছে
        sent_message = await message.forward(STORAGE_CHANNEL_ID)
        
        # ফাইল সংক্রান্ত তথ্য সংগ্রহ করা হচ্ছে
        media = sent_message.document or sent_message.video or sent_message.audio
        file_name = media.file_name
        file_size = media.file_size
        
        # ডাটাবেসে ফাইলের তথ্য সংরক্ষণ করা হচ্ছে
        file_doc = {
            "filename": file_name,
            "size": file_size,
            "message_id": sent_message.id, # চ্যানেলের মেসেজ আইডি
            "uploaded_at": datetime.datetime.utcnow(),
        }
        result = files_collection.insert_one(file_doc)

        # ডাউনলোড লিঙ্ক তৈরি করা হচ্ছে
        download_id = str(result.inserted_id)
        download_url = f"{BASE_URL}/download/{download_id}"
        
        await user_message.edit_text(
            f"✅ **Upload Complete!**\n\n**File:** `{file_name}`\n\n🔗 [Get Download Link]({download_url})",
            disable_web_page_preview=True,
        )

    except Exception as e:
        await user_message.edit_text(f"⚠️ An error occurred:\n`{str(e)}`")

print("✅ Bot is running successfully...")
app.run()
