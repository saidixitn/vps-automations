#!/bin/bash

# Configuration
REPO_DIR="/home/dixit/pm2_backup"
SOURCE_DASHBOARD="/home/jobiak_dashboard"
SOURCE_DIXIT="/home/dixit"

# 1. Sync files to backup repo (Adding __pycache__ to exclusions)
rsync -av --delete \
    --exclude='venv/' \
    --exclude='logs/' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    "$SOURCE_DASHBOARD/" "$REPO_DIR/jobiak_dashboard_backup/"

rsync -av --delete \
    --exclude='venv/' \
    --exclude='logs/' \
    --exclude='.git/' \
    --exclude='pm2_backup/' \
    --exclude='__pycache__/' \
    "$SOURCE_DIXIT/" "$REPO_DIR/dixit_backup/"

# 2. Update environment data
cd "$SOURCE_DASHBOARD"
./venv/bin/pip freeze > "$REPO_DIR/requirements.txt"
pm2 jlist > "$REPO_DIR/pm2_snapshot.json"

# 3. Git Logic
cd "$REPO_DIR"
git add .

# Only push if there are actual changes
if git diff --cached --quiet; then
    echo "No changes detected. Skipping push."
else
    echo "Changes detected. Committing and pushing to GitHub..."
    git commit -m "Automated VPS Backup: $(date +'%Y-%m-%d %H:%M')"
    git push origin main
fi
