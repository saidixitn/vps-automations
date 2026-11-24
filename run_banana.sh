#!/bin/bash
cd /home/dixit/

# This checks if you provided a date. If not, it uses 'yesterday'.
TARGET_DATE=${1:-$(date -d "yesterday" '+%Y-%m-%d')}

/home/dixit/venv/bin/python3 banana.py "$TARGET_DATE"
