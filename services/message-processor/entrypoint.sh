#!/usr/bin/env bash
set -euo pipefail

echo "[*] Running DB migrations…"
psql "$DATABASE_URL" \
  -f migrations/001_create_receipts_table.sql

echo "[*] Starting message-processor…"
exec python processor.py
