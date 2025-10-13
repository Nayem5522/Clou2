import math
import asyncio

async def progress_callback(current, total, message, stage):
    try:
        percent = math.floor(current * 100 / total)
        bar = "▰" * (percent // 10) + "▱" * (10 - (percent // 10))
        await message.edit_text(f"{stage}...\n\n[{bar}] {percent}%")
        await asyncio.sleep(0.5)
    except:
        pass
