import io
import os
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException
from pymongo import MongoClient, UpdateOne
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()
# =====================================================
# ROUTER
# =====================================================
router = APIRouter(prefix="/semrush", tags=["SEMrush"])

# =====================================================
# CONFIG
# =====================================================
MONGO_URI =  os.getenv("MONGO_URI")

DB_NAME = "domain_expires"
COLLECTION_NAME = "semrush_url's"
URL_COLUMN = "URL"

# =====================================================
# MONGO (INIT ONCE)
# =====================================================
client = MongoClient(MONGO_URI)
collection = client[DB_NAME][COLLECTION_NAME]

# Create index ONCE (idempotent & authenticated)
collection.create_index("url", unique=True)

# =====================================================
# HELPERS
# =====================================================
def extract_domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host

# =====================================================
# ENDPOINT
# =====================================================
@router.post("/upload")
async def upload_semrush_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content), dtype=str)
    except Exception as e:
        raise HTTPException(400, f"Failed to read CSV: {e}")

    if URL_COLUMN not in df.columns:
        raise HTTPException(400, f"CSV must contain '{URL_COLUMN}' column")

    urls = (
        df[URL_COLUMN]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if not urls:
        return {"inserted": 0, "total_urls_found": 0}

    ops = []
    for url in urls:
        ops.append(
            UpdateOne(
                {"url": url},
                {
                    "$setOnInsert": {
                        "domain": extract_domain(url),
                        "url": url,
                    }
                },
                upsert=True,
            )
        )

    result = collection.bulk_write(ops, ordered=False)

    return {
        "total_urls_found": len(urls),
        "inserted": result.upserted_count,
    }
