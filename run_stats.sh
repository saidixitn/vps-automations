#!/bin/bash

# 1. Go to the correct directory
cd /home/dixit

# 2. Get the current hour in 24-hour format (00 to 23)
CURRENT_HOUR=$(date +%H)

# 3. Decide the date based on the hour
if [ "$CURRENT_HOUR" -lt 12 ]; then
    # If it's morning (10 AM), run for yesterday
    TARGET_DATE=$(date -d "yesterday" '+%Y-%m-%d')
    echo "Running 10 AM Morning Report for: $TARGET_DATE"
else
    # If it's afternoon (3 PM), run for today
    TARGET_DATE=$(date '+%Y-%m-%d')
    echo "Running 3 PM Afternoon Report for: $TARGET_DATE"
fi

# 4. Run the python script with the target date
/home/dixit/venv/bin/python stats_email.py "$TARGET_DATE"
