#!/usr/bin/env python3
import os
import json
import time
import pika
import pika.exceptions
import psycopg2
from psycopg2.extras import Json, DictCursor

# ─── Config from env ─────────────────────────────────────────────
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
QUEUE_NAME   = os.environ.get("QUEUE_NAME", "receipt_queue")
DATABASE_URL = os.environ["DATABASE_URL"]

# ─── Postgres setup ──────────────────────────────────────────────
db_conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
db_conn.autocommit = True
db      = db_conn.cursor()

# ─── Helper: connect to RabbitMQ with retry ──────────────────────
def connect_rabbitmq(url, queue, backoff=5):
    params = pika.URLParameters(url)
    while True:
        try:
            print(f"[*] Connecting to RabbitMQ at {url} …", flush=True)
            conn    = pika.BlockingConnection(params)
            channel = conn.channel()
            channel.queue_declare(queue=queue, durable=True)
            channel.basic_qos(prefetch_count=1)
            print(f"[✓] RabbitMQ connected and queue '{queue}' declared", flush=True)
            return conn, channel
        except pika.exceptions.AMQPConnectionError as e:
            print(f"[!] RabbitMQ not ready ({e}), retrying in {backoff}s…", flush=True)
            time.sleep(backoff)

# ─── Establish RabbitMQ connection ───────────────────────────────
conn, channel = connect_rabbitmq(RABBITMQ_URL, QUEUE_NAME)

print(f"[+] Waiting for messages on '{QUEUE_NAME}'…", flush=True)

# ─── Message handlers ────────────────────────────────────────────
def handle_receipt(msg):
    user = msg.get("user", {})
    receipt = msg.get("receipt", {})

    # fallback to nested values if top‐level is null
    total_amount = msg.get("total_amount") or receipt.get("total_amount")
    date         = msg.get("date")         or receipt.get("date")

    db.execute(
        """
        INSERT INTO receipts
          (user_id, username, total_amount, date, raw)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user.get("id"),
            user.get("username"),
            total_amount,
            date,
            Json(msg)
        )
    )
    print(f"[✓] Stored receipt for {user.get('username')}", flush=True)


def dispatch(msg):
    action = msg.get("action")
    if action == "receipt_extraction":
        handle_receipt(msg)
    else:
        print(f"[!] Unknown action '{action}', skipping", flush=True)

def callback(ch, method, properties, body):
    try:
        msg = json.loads(body)
        dispatch(msg)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print(f"[!] Error processing message: {e}", flush=True)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

# ─── Kick off consuming ──────────────────────────────────────────
channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

try:
    channel.start_consuming()
except KeyboardInterrupt:
    print("Interrupted, shutting down", flush=True)
finally:
    # close the correct connection objects
    channel.close()
    conn.close()
    db.close()
    db_conn.close()
