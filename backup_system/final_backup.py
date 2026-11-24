import os
import sys
import subprocess
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
BASE_DIR = "/home/dixit/backup_system"
BACKUP_DIR = os.path.join(BASE_DIR, "dumps")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
FOLDER_ID = "1bkoyVxf6JBoQJYuihPM7CaFKDn_Wfwj3"
SCOPES = ['https://www.googleapis.com/auth/drive.file']
MONGODB_URI = os.getenv("MONGO_URI")

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

def get_drive_service():
    """Authenticates and returns the Google Drive service."""
    creds = None
    
    # Modern approach: Parse standard JSON token, not pickle
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing Google Drive token...")
            creds.refresh(Request())
        else:
            # If no valid token, you must run this locally once to generate it
            print("Error: token.json missing or invalid. Please re-authenticate.")
            # Note: Do not run InstalledAppFlow on a headless VPS
            return None
            
        # Save the refreshed credentials back to the JSON file
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
    return build('drive', 'v3', credentials=creds)

def execute_backup_lifecycle():
    file_path = None
    client = None
    success = False

    try:
        if not MONGODB_URI:
            raise ValueError("MONGO_URI environment variable is missing.")

        # 1. Verify Connection
        print("Verifying MongoDB connection...")
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("MongoDB connection verified.")

        # 2. Create GZIP Backup (Secure Subprocess)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        file_name = f"full_mongodb_backup_{timestamp}.gz"
        file_path = os.path.join(BACKUP_DIR, file_name)

        print(f"Creating compressed backup: {file_name}")
        
        # Using list format to avoid shell=True vulnerabilities
        mongodump_command = [
            "mongodump",
            "--uri", MONGODB_URI,
            f"--archive={file_path}",
            "--gzip"
        ]
        
        subprocess.run(
            mongodump_command, 
            check=True, 
            capture_output=True, 
            text=True
        )

        # 3. Upload to Google Drive
        service = get_drive_service()
        if not service:
            raise Exception("Failed to initialize Google Drive service.")

        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype='application/gzip', resumable=True)

        print(f"Uploading {file_name} to Google Drive...")
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Upload Progress: {int(status.progress() * 100)}%")
        
        print(f"Success! Drive File ID: {response.get('id')}")
        success = True

    except subprocess.CalledProcessError as e:
        print(f"CRITICAL ERROR (mongodump failed): {e.stderr}")
    except PyMongoError as e:
        print(f"CRITICAL ERROR (Database): {e}")
    except Exception as e:
        print(f"CRITICAL ERROR (System/Upload): {e}")
        
    finally:
        # Close DB connection
        if client:
            client.close()
            print("MongoDB connection closed.")
            
        # 4. Cleanup - ALWAYS delete the local file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            print("Local file deleted. VPS storage is clean.")
            
        # Exit properly so system knows if it failed or succeeded
        if success:
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    execute_backup_lifecycle()