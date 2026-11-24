import gspread
from google.oauth2.service_account import Credentials
from pymongo import MongoClient

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_gspread_client(mongo_uri: str):
    client = MongoClient(mongo_uri)
    doc = client["google_creds"]["creds"].find_one(
        {"name": "google_credentials"},
        {"_id": 0, "content": 1}
    )

    if not doc or "content" not in doc:
        raise RuntimeError("Google credentials not found in MongoDB")

    creds = Credentials.from_service_account_info(
        doc["content"],
        scopes=SCOPES
    )
    return gspread.authorize(creds)
