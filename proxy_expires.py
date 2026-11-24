import pymongo
from datetime import datetime, timedelta, timezone
import sys
import concurrent.futures
import time
import os
from dotenv import load_dotenv
load_dotenv()
# --------------------------------------------------
# CONFIG
# --------------------------------------------------
LOCAL_MONGO_URI =  os.getenv("MONGO_URI")
CREDS_DB = "mongo_creds"

# prod_jobiak_ai is used for both the lookup key and the actual DB name
DOMAIN_KEY = "prod_jobiak_ai"
TARGET_DB = "prod_jobiak_ai"
EMPLOYER_ID = "68b8133b060e8f5df1a6c3a7"

LOCAL_DB = "domain_expires"
EXPORT_COLLECTION = "earnhaus_expires"

# Semrush Config
SEMRUSH_MONGO_URI = "mongodb://localhost:27017/"
SEMRUSH_DB_NAME = "domain_expires"
SEMRUSH_COLLECTION = "semrush_url's"
SEMRUSH_MATCH_DOMAIN = "earnhaus.com"

DAYS = 30
CHUNK_SIZE = 10_000
MAX_WORKERS = 3


# --------------------------------------------------
# WORKER FUNCTIONS
# --------------------------------------------------

def fetch_jobs(db):
    """Worker 1: Fetch active jobs for Earnhaus."""
    print(f"  [Worker: Jobs] Querying {TARGET_DB}.job...")

    local_jobs = {}
    query = {
        "employerId": EMPLOYER_ID,
        "status": "posted",
        "datePosted": {"$exists": True}
    }

    projection = {
        "_id": 0,
        "jobId": 1,
        "validThrough": 1,
        "submittedUrl": 1,
        "jobtitle": 1,
        "company": 1
    }

    cursor = db["job"].find(query, projection)

    count = 0
    for doc in cursor:
        jid = doc.get("jobId")
        if jid:
            local_jobs[jid] = doc
            count += 1

    cursor.close()
    print(f"  [Worker: Jobs] Finished. Found {count:,} jobs.")
    return local_jobs


def fetch_views(db, start_date, end_date):
    """Worker 2: Fetch viewed job IDs based on your specific find query."""
    print(f"  [Worker: Views] Querying {TARGET_DB}.userAnalytics...")

    local_viewed_keys = set()

    # Updated to match your find() query exactly
    query = {
        "employerId": EMPLOYER_ID,
        "isBot": False,
        "browserType": {"$ne": "Unknown"},
        "deviceType": {"$ne": "Unknown"},
        "isFromGoogle": True,
        "createdDt": {
            "$gt": start_date,
            "$lt": end_date
        }
    }

    # Projecting only jobId as per your request
    cursor = db["userAnalytics"].find(query, {"jobId": 1})

    count = 0
    for doc in cursor:
        jid = doc.get("jobId")
        if jid:
            local_viewed_keys.add(jid)
            count += 1

    cursor.close()
    print(f"  [Worker: Views] Finished. Found {count:,} job views.")
    return local_viewed_keys


def fetch_semrush(uri, db_name, col_name, match_domain):
    """Worker 3: Fetch Semrush whitelist URLs."""
    print(f"  [Worker: Semrush] Querying whitelist for {match_domain}...")

    local_semrush_urls = set()
    client = pymongo.MongoClient(uri)
    db = client[db_name]

    query = {
        "view_exists": {"$exists": False},
        "domain": match_domain
    }

    cursor = db[col_name].find(query, {"url": 1})

    count = 0
    for doc in cursor:
        if "url" in doc:
            local_semrush_urls.add(doc["url"])
            count += 1

    client.close()
    print(f"  [Worker: Semrush] Finished. Found {count:,} whitelist URLs.")
    return local_semrush_urls


# --------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------
if __name__ == "__main__":
    print(f"\n========== STARTING EARNHAUS EXPIRY PROCESS ==========\n")
    start_time = time.time()

    # 1. Date Setup
    now = datetime.now(timezone.utc)
    START_DATE = now - timedelta(days=DAYS)
    END_DATE = now

    # 2. Database Setup
    local_client = pymongo.MongoClient(LOCAL_MONGO_URI)
    creds_db = local_client[CREDS_DB]

    # Look up the URI using prod_jobiak_ai
    creds = creds_db["creds"].find_one({"domain": DOMAIN_KEY}, {"mongo_uri": 1})
    if not creds:
        sys.exit(f"Critical Error: domain '{DOMAIN_KEY}' not found in {CREDS_DB}.creds")

    prod_client = pymongo.MongoClient(creds["mongo_uri"])
    prod_db = prod_client[TARGET_DB]

    export_db = local_client[LOCAL_DB]
    export_col = export_db[EXPORT_COLLECTION]

    # 3. Multi-threaded Fetching
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        f_jobs = executor.submit(fetch_jobs, prod_db)
        f_views = executor.submit(fetch_views, prod_db, START_DATE, END_DATE)
        f_semrush = executor.submit(fetch_semrush, SEMRUSH_MONGO_URI, SEMRUSH_DB_NAME, SEMRUSH_COLLECTION,
                                    SEMRUSH_MATCH_DOMAIN)

        jobs_dict = f_jobs.result()
        viewed_ids = f_views.result()
        semrush_urls = f_semrush.result()

    # 4. Comparison Logic
    all_job_ids = set(jobs_dict.keys())
    no_view_ids = all_job_ids - viewed_ids

    final_expiry_docs = []
    semrush_skipped = 0

    for jid in no_view_ids:
        job_doc = jobs_dict[jid]
        url = job_doc.get("submittedUrl")

        if url and url in semrush_urls:
            semrush_skipped += 1
            continue

        final_expiry_docs.append(job_doc)

    # 5. Output and Export
    print(f"\nAnalysis Summary:")
    print(f"  • Total Active Jobs   : {len(all_job_ids):,}")
    print(f"  • Jobs with Views     : {len(viewed_ids):,}")
    print(f"  • Semrush Protected   : {semrush_skipped:,}")
    print(f"  ✓ Net Jobs to Expire  : {len(final_expiry_docs):,}\n")

    if final_expiry_docs:
        if EXPORT_COLLECTION in export_db.list_collection_names():
            export_db.drop_collection(EXPORT_COLLECTION)

        # Batch insert for speed
        for i in range(0, len(final_expiry_docs), CHUNK_SIZE):
            export_col.insert_many(final_expiry_docs[i:i + CHUNK_SIZE])

        print(f"SUCCESS: Data saved to local collection '{EXPORT_COLLECTION}'.")
    else:
        print("No records matched expiry criteria.")

    elapsed = time.time() - start_time
    print(f"\n========== TOTAL RUN TIME: {elapsed:.2f}s ==========\n")