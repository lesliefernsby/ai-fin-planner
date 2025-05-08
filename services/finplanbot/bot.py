#!/usr/bin/env python3
import os, sys, base64, openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from PIL import Image
from io import BytesIO

# ─────────────── Debug Start ───────────────
print("DEBUG: starting bot.py", flush=True)

# Load environment variables
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

    # Build the chat messages using the provided approach
    messages = [
        {
            "role": "system",
            "content": (
                "You are a specialized OCR assistant designed to extract structured information from receipts. "
                "Carefully extract the following fields from the receipt image: "
                "- Store Name\n"
                "- Date (format as YYYY-MM-DD if available)\n"
                "- Total Amount\n"
                "- List of Items Purchased (including item name and price)\n\n"
                "If any of these fields are not present, indicate them as 'N/A'. "
                "Output the extracted information in JSON format. "
                "Ensure the JSON is well-structured and valid. "
                "Categorize the receipt into a category like 'Groceries', 'Electronics', etc., if possible. "
            )
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "extract the data from this receipt and output into JSON"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}}
            ]
        }
    ]

    # Call OpenAI with the up-to-date namespaced method
    resp = openai.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages
    )
    text = resp.choices[0].message.content.strip()

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
