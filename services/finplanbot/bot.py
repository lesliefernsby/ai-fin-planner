#!/usr/bin/env python3
import os, sys, base64, openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from PIL import Image
from io import BytesIO
import yaml
import json
from pathlib import Path
import pika

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
if not RABBITMQ_URL:
    print("ERROR: RABBITMQ_URL is not set!", flush=True)
    sys.exit(1)

# One connection/channel per process
params  = pika.URLParameters(RABBITMQ_URL)
conn    = pika.BlockingConnection(params)
channel = conn.channel()
# Declare a durable queue named "receipt_queue"
channel.queue_declare(queue="receipt_queue", durable=True)

with open(Path(__file__).parent / "config" / "prompts.yaml") as f:
    PROMPTS = yaml.safe_load(f)

CONFIG_DIR = Path(__file__).parent / "config"
SCHEMA = json.loads((CONFIG_DIR / "receipt_schema.json").read_text(encoding="utf-8"))
SCHEMA_STR = json.dumps(SCHEMA, indent=2)

sys_msg = PROMPTS["receipt_extraction"]["system"]
usr_msg = PROMPTS["receipt_extraction"]["user"]
# ─────────────── Environment Variables ───────────────
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

if not BOT_TOKEN:
    print("ERROR: TELEGRAM_TOKEN is not set!", flush=True)
    sys.exit(1)
if not OPENAI_KEY:
    print("ERROR: OPENAI_KEY is not set!", flush=True)
    sys.exit(1)

print("DEBUG: got token and key", flush=True)
openai.api_key = OPENAI_KEY

# ─────────────── Image Utilities ───────────────
def resize_image_bytes(img_bytes, max_size=(768, 768)):
    with Image.open(BytesIO(img_bytes)) as img:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=40)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

# ─────────────── Handlers ───────────────
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Processing receipt...")
    photo_list = update.message.photo
    if not photo_list:
        await update.message.reply_text("Please send a photo of a receipt.")
        return

    # Download the highest-resolution photo
    photo = photo_list[-1]
    file = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()

    # Resize and encode
    img_b64 = resize_image_bytes(img_bytes)

    messages = [
        {
            "role": "system",
            "content": f"{sys_msg}\n\n{SCHEMA_STR}"
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": usr_msg},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}}
            ]
        }
    ]

    resp = openai.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages
    )
    text = resp.choices[0].message.content.strip()


    try:
        receipt_json = json.loads(text)
    except json.JSONDecodeError:
        receipt_json = {"raw": text}

    payload = {
        "user": {
            "id": update.effective_user.id,
            "username": update.effective_user.username
        },
        "receipt": receipt_json
    }
    channel.basic_publish(
        exchange="",
        routing_key="receipt_queue",
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            delivery_mode=2  # make message persistent
        )
    )

    # Reply with the extracted JSON
    await update.message.reply_text(f"<pre>{text}</pre>", parse_mode="HTML")

# ─────────────── Main ───────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.PHOTO, handle_receipt))

    print("Bot is running...", flush=True)
    app.run_polling()

if __name__ == "__main__":
    main()
