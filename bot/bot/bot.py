# --- START OF FILE bot/bot.py ---

from pyrogram import Client, filters
from pyrogram.types import Message, MessageEntity
from bot.config import BOT_TOKEN, API_ID, API_HASH, BASE_URL
import aiohttp, traceback

app = Client("r2s-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# /start message
@app.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    await message.reply_text(
        "👋 **Welcome to Link Generator Bot**\n\n"
        "🔗 Send me any direct download link, and I’ll give you a new proxied link.\n\n"
        "⚙️ **Powered by Render + MongoDB**"
    )

# URL handler
@app.on_message(filters.text & filters.entity("url"))
async def handle_link(client, message: Message):
    url_entity = next((e for e in message.entities if e.type == "url"), None)
    if not url_entity:
        return # Should not happen due to filters, but as a safeguard.

    original_url = message.text[url_entity.offset : url_entity.offset + url_entity.length]
    
    sent = await message.reply_text("⏳ Processing your link...")

    try:
        payload = {"url": original_url}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BASE_URL}/api/add_link", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success":
                        link_id = data["link"]["_id"]
                        filename = data["link"]["filename"]
                        download_page_url = f"{BASE_URL}/download/{link_id}"
                        
                        await sent.edit_text(
                            f"✅ **Link Generated!**\n\n"
                            f"**File:** `{filename}`\n\n"
                            f"🔗 [Open Download Page]({download_page_url})",
                            disable_web_page_preview=True,
                        )
                    else:
                        await sent.edit_text(f"❌ Failed to process link: {data.get('message')}")
                else:
                    error_text = await resp.text()
                    await sent.edit_text(f"❌ Server returned an error (Status: {resp.status}):\n`{error_text}`")

    except Exception as e:
        await sent.edit_text(f"⚠️ An error occurred:\n`{traceback.format_exc()}`")

print("✅ Bot is running successfully...")
app.run()

# --- END OF FILE bot/bot.py ---
