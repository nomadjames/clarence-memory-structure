#!/bin/bash
# vault-sync.sh — Sync Obsidian vault to Google Drive
# Runs via cron every 2 hours

VAULT_DIR="/home/james/.openclaw/workspace"
REMOTE="gdrive:openclaw-workspace"
LOG="/tmp/vault-sync.log"

echo "$(date): Starting vault sync to $REMOTE" >> "$LOG"

rclone sync "$VAULT_DIR" "$REMOTE" \
    --exclude ".obsidian/workspace.json" \
    --exclude ".obsidian/workspace-mobile.json" \
    --exclude ".trash/**" \
    --log-file="$LOG" \
    --log-level INFO \
    2>&1

echo "$(date): Vault sync complete" >> "$LOG"

# Also run the indexer
/home/james/.openclaw/workspace/scripts/vault-index.sh
