# bot/bot.py
# Updated, fixed and more robust Pyrogram bot handler

from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config import BOT_TOKEN, API_ID, API_HASH, BASE_URL
import aiohttp
import asyncio
import logging

logging.basicConfig(level=logging.INFO)

app = Client("r2s-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# /start
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    await message.reply_text(
        "👋 **Welcome to Link Generator Bot**\n\n"
        "🔗 Send me any direct download link and I'll create a proxied download page.\n\n"
        "🛠️ If you want to manage links use the website dashboard."
    )

# Helper to POST to server API
async def create_link_on_server(original_url: str, filename: str = None):
    if not BASE_URL:
        raise RuntimeError("BASE_URL not configured in bot.config")
    payload = {"url": original_url}
    if filename:
        payload['filename'] = filename

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{BASE_URL.rstrip('/')}/api/add_link", json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                else:
                    text = await resp.text()
                    return {"status": "error", "message": f"Server responded {resp.status}: {text}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# When user sends a message that contains a URL
@app.on_message(filters.text & ~filters.edited)
async def handle_text(client: Client, message: Message):
    text = message.text or ""
    # quick URL detection: look for http(s)://
    if "http://" not in text and "https://" not in text:
        return

    sent = await message.reply_text("🔎 Processing your link... Please wait...")

    # Optional: extract a naive filename from message or url
    filename = None
    parts = text.strip().split()
    # find the first token that looks like a URL
    url = next((p for p in parts if p.startswith('http://') or p.startswith('https://')), None)
    if not url:
        await sent.edit_text("❌ No valid URL found in your message.")
        return

    try:
        server_resp = await create_link_on_server(url, filename)
        if server_resp.get('status') == 'success' and server_resp.get('link'):
            link = server_resp['link']
            link_id = link.get('_id')
            filename = link.get('filename') or filename or url.split('/')[-1]
            download_page = f"{BASE_URL.rstrip('/')}/download/{link_id}"

            await sent.edit_text(
                f"✅ Link created: **{filename}**\n\n"
                f"Open download page: {download_page}",
                disable_web_page_preview=True,
            )
        else:
            await sent.edit_text(f"❌ Failed to create link: {server_resp.get('message', 'Unknown error')}")
    except Exception as e:
        await sent.edit_text(f"⚠️ Unexpected error:\n`{str(e)}`")


if __name__ == '__main__':
    print("✅ Bot is running...")
    app.run()
