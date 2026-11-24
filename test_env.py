import os
from dotenv import load_dotenv
load_dotenv()
import sys
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, UpdateOne
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytz import timezone as pytz_timezone
from gspread.utils import rowcol_to_a1
import json
import tempfile

# ============================================
# === ENV & CONFIG (LOCAL + PROD FRIENDLY) ===
# ============================================

# Main root Mongo URI
REMOTE_MONGO_URI =  os.getenv("MONGO_URI")
print(REMOTE_MONGO_URI)