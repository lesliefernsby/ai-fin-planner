#!/usr/bin/env python3
import os
import sys
import time
import json
import base64

import pika
import pika.exceptions
import openai
import yaml

from pathlib import Path
from io import BytesIO
from PIL import Image
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─── Configuration from env ─────────────────────────────────────────────
RABBITMQ_URL = os.getenv("RABBITMQ_URL")
if not RABBITMQ_URL:
    print("ERROR: RABBITMQ_URL is not set!", flush=True)
    sys.exit(1)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")
if not BOT_TOKEN:
    print("ERROR: TELEGRAM_TOKEN is not set!", flush=True)
    sys.exit(1)
if not OPENAI_KEY:
    print("ERROR: OPENAI_KEY is not set!", flush=True)
    sys.exit(1)

# ─── OpenAI setup ────────────────────────────────────────────────────────
openai.api_key = OPENAI_KEY

# ─── Load prompts & schema ───────────────────────────────────────────────
CONFIG_DIR = Path(__file__).parent / "config"
with open(CONFIG_DIR / "prompts.yaml", encoding="utf-8") as f:
    PROMPTS = yaml.safe_load(f)

SCHEMA = json.loads((CONFIG_DIR / "receipt_schema.json").read_text(encoding="utf-8"))
SCHEMA_STR = json.dumps(SCHEMA, indent=2)

sys_msg = PROMPTS["receipt_extraction"]["system"]
usr_msg = PROMPTS["receipt_extraction"]["user"]

# ─── RabbitMQ helper ─────────────────────────────────────────────────────
QUEUE_NAME = "receipt_queue"

def connect_rabbitmq(url, queue, backoff=5):
    params = pika.URLParameters(url)
    while True:
        try:
            print(f"[*] Connecting to RabbitMQ at {url} …", flush=True)
            conn = pika.BlockingConnection(params)
            ch   = conn.channel()
            ch.queue_declare(queue=queue, durable=True)
            print(f"[✓] RabbitMQ connected; queue '{queue}' declared", flush=True)
            return conn, ch
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[!] RabbitMQ not ready ({e!r}), retrying in {backoff}s…", flush=True)
            time.sleep(backoff)

# Establish RabbitMQ connection and channel once, at startup
conn, channel = connect_rabbitmq(RABBITMQ_URL, QUEUE_NAME)

# ─── Image utility ────────────────────────────────────────────────────────
def resize_image_bytes(img_bytes, max_size=(768, 768)):
    with Image.open(BytesIO(img_bytes)) as img:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=40)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

# ─── Telegram handlers ────────────────────────────────────────────────────
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Processing receipt…")
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("Please send a photo of a receipt.")
        return

    # Download highest-res photo
    file = await context.bot.get_file(photos[-1].file_id)
    img_bytes = await file.download_as_bytearray()
    img_b64   = resize_image_bytes(img_bytes)

    # Build messages for OpenAI
    messages = [
        {"role": "system", "content": f"{sys_msg}\n\n{SCHEMA_STR}"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": usr_msg},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}",
                        "detail": "high",
                    },
                },
            ],
        },
    ]

    # Call OpenAI
    resp = openai.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages
    )
    text = resp.choices[0].message.content.strip()

    # Attempt to parse JSON, fallback to raw text
    try:
        receipt_json = json.loads(text)
    except json.JSONDecodeError:
        receipt_json = {"raw": text}

    # Build payload & publish to RabbitMQ
    payload = {
        "user": {
            "id": update.effective_user.id,
            "username": update.effective_user.username,
        },
        "action":    "receipt_extraction",
        "operation": "spending",
        "total_amount": receipt_json.get("total_amount"),
        "date":         receipt_json.get("date"),
        "receipt":      receipt_json,
    }

    channel.basic_publish(
        exchange="",
        routing_key=QUEUE_NAME,
        body=json.dumps(payload),
        properties=pika.BasicProperties(delivery_mode=2),
    )

    # Respond to user
    await update.message.reply_text(f"<pre>{text}</pre>", parse_mode="HTML")

# ─── Bot entrypoint ────────────────────────────────────────────────────────
def main():
    print("DEBUG: got token and key", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.PHOTO, handle_receipt))

    print("Bot is running…", flush=True)
    app.run_polling()

if __name__ == "__main__":
    main()
