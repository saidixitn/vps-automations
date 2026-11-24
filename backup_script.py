import os
import subprocess
import datetime
import logging
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv()

# ================= CONFIGURATION =================
MONGO_URI = os.getenv("MONGO_URI")
CREDS_DB = "google_creds"         
CREDS_COLLECTION = "creds"
BACKUP_DIR = "/root/mongodb_backups"

# Your Folder ID and Personal Email for Quota Transfer
PARENT_FOLDER_ID = '1bkoyVxf6JBoQJYuihPM7CaFKDn_Wfwj3' 
PERSONAL_EMAIL = 'saidixitn@gmail.com' 

# Use the full drive scope for ownership transfer permissions
SCOPES = ['https://www.googleapis.com/auth/drive']

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# =================================================

def get_creds_from_mongo():
    try:
        logging.info("Connecting to MongoDB to fetch credentials...")
        client = MongoClient(MONGO_URI)
        db = client[CREDS_DB]
        doc = db[CREDS_COLLECTION].find_one({"name": "google_credentials"}, {"content": 1})
        if not doc or "content" not in doc:
            raise ValueError("Credentials document not found in DB!")
        return doc["content"]
    except Exception as e:
        logging.error(f"Failed to fetch credentials: {e}")
        return None

def create_full_backup():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"FULL_MONGO_BACKUP_{timestamp}.gz"
    filepath = os.path.join(BACKUP_DIR, filename)

    logging.info("Starting FULL MongoDB Dump...")
    cmd = ["mongodump", f"--uri={MONGO_URI}", f"--archive={filepath}", "--gzip"]

    try:
        subprocess.run(cmd, check=True)
        logging.info(f"Full backup archive created: {filename}")
        return filepath, filename
    except subprocess.CalledProcessError as e:
        logging.error(f"mongodump failed: {e}")
        return None, None

def upload_to_drive(file_path, file_name, creds_dict):
    try:
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {'name': file_name, 'parents': [PARENT_FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype='application/gzip', resumable=True)
        
        logging.info(f"Uploading {file_name} (Initiating Resumable Upload)...")
        
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True,
            supportsTeamDrives=True
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logging.info(f"Upload progress: {int(status.progress() * 100)}%")

        file_id = response.get('id')
        logging.info(f"Upload Success! ID: {file_id}. Attempting Ownership Transfer...")

        # Transfer ownership to your personal 5TB account
        permission_body = {'role': 'owner', 'type': 'user', 'emailAddress': PERSONAL_EMAIL}
        service.permissions().create(
            fileId=file_id,
            body=permission_body,
            transferOwnership=True,
            supportsAllDrives=True
        ).execute()

        logging.info("Ownership transferred. Storage now counts against your 5TB plan.")
        return True
    except Exception as e:
        logging.error(f"Drive error: {e}")
        return False

def main():
    creds_dict = get_creds_from_mongo()
    if not creds_dict: return
    file_path, file_name = create_full_backup()
    if file_path and os.path.exists(file_path):
        if upload_to_drive(file_path, file_name, creds_dict):
            os.remove(file_path)
            logging.info("Cleaned up local file.")

if __name__ == "__main__":
    main()
