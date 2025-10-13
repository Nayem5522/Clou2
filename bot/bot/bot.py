from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config import BOT_TOKEN, API_ID, API_HASH, BASE_URL
from bot.utils import progress_callback
import aiohttp, os, asyncio, traceback

app = Client("r2s-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# /start message
@app.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    await message.reply_text(
        "👋 **Welcome to R2S File Uploader Bot**\n\n"
        "📤 Send me any file or video, and I’ll upload it to the server.\n"
        "🔗 Then I’ll give you a direct download link.\n\n"
        "⚙️ **Powered by Render + MongoDB**"
    )

# File handler
@app.on_message(filters.document | filters.video | filters.audio)
async def handle_file(client, message: Message):
    sent = await message.reply_text("📥 Downloading your file from Telegram...")

    try:
        file_path = await message.download(progress=progress_callback, progress_args=(sent, "📥 Downloading"))

        await sent.edit_text("☁️ Uploading to Render server...")

        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("file", f, filename=os.path.basename(file_path))
                async with session.post(f"{BASE_URL}/api/upload", data=form) as resp:
                    data = await resp.json()

        os.remove(file_path)

        if data.get("status") == "success":
            link = data.get("download_url")
            await sent.edit_text(
                f"✅ **Upload Complete!**\n\n🔗 [Download File Here]({link})",
                disable_web_page_preview=True,
            )
        else:
            await sent.edit_text(f"❌ Upload failed: {data.get('message')}")

    except Exception as e:
        await sent.edit_text(f"⚠️ Error occurred:\n`{traceback.format_exc()}`")

print("✅ Bot is running successfully...")
app.run()
