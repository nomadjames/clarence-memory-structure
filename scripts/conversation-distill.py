#!/usr/bin/env python3
"""
conversation-distill.py — Extract durable knowledge from Telegram conversations.

This is a thin wrapper around rag-pipeline/distillation.py (the canonical
implementation). All logic lives there; this script exists so cron jobs
and docs can reference scripts/conversation-distill.py without breaking.

Usage:
  python3 conversation-distill.py                    # distill last 24h of sessions
  python3 conversation-distill.py --hours 72         # custom window
  python3 conversation-distill.py --backfill         # process ALL sessions (first run)
  python3 conversation-distill.py --dry-run          # show what would be extracted
  python3 conversation-distill.py --session FILE     # process a specific session file
  python3 conversation-distill.py --max-batches 10   # cap batches per session (resumes next run)
"""

import sys
import os

# Add rag-pipeline to path so we can import the canonical module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-pipeline"))

from distillation import main

if __name__ == "__main__":
    main()
