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
LOCAL_MONGO_URI = os.getenv("MONGO_URI")
CREDS_DB = "mongo_creds"

DOMAIN = "earnwithwfh_prod"
TARGET_DB = DOMAIN

LOCAL_DB = "domain_expires"
EXPORT_COLLECTION = f"{DOMAIN}_expires"

# Semrush Config
SEMRUSH_MONGO_URI = "mongodb://localhost:27017/"
SEMRUSH_DB_NAME = "domain_expires"
SEMRUSH_COLLECTION = "semrush_url's"
SEMRUSH_MATCH_DOMAIN = "earnwithwfh.com"  # Added: Filter specific domain in Semrush DB

DAYS = 30
CHUNK_SIZE = 10_000
MAX_WORKERS = 3  # Parallel threads


# --------------------------------------------------

# --------------------------------------------------
# WORKER FUNCTIONS
# --------------------------------------------------

def fetch_jobs(db, start_date, end_date):
    """Worker 1: Fetch all active jobs."""
    print("  [Worker: Jobs] Started fetching from Target_P4_Opt...")

    local_jobs = {}
    pipeline = [
        {
            "$match": {
                "employerId": {"$exists": True},
                "job_status": {"$ne": "3.0"},
                "gpost": 5.0,
                "gpost_date": {
                    "$gt": start_date,
                    "$lt": end_date
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "uniqueKey": 1,
                "company": 1,
                "jobtitle": 1,
                "gpost_date": 1,
                "employerId": 1,
                "pub_expired": 1,
                "submittedUrl": 1
            }
        }
    ]

    # Note: Pass client/db is thread-safe in PyMongo
    cursor = db["Target_P4_Opt"].aggregate(pipeline, allowDiskUse=True)

    count = 0
    for doc in cursor:
        if "uniqueKey" in doc:
            local_jobs[doc["uniqueKey"]] = doc
            count += 1

    cursor.close()
    print(f"  [Worker: Jobs] Finished. Found {count:,} jobs.")
    return local_jobs


def fetch_views(db, start_date, end_date):
    """Worker 2: Fetch viewed job IDs."""
    print("  [Worker: Views] Started fetching from userAnalytics...")

    local_viewed_keys = set()
    pipeline = [
        {
            "$match": {
                "isBot": False,
                "browserType": {"$ne": "Unknown"},
                "deviceType": {"$ne": "Unknown"},
                "isFromGoogle": True,
                "createdDt": {
                    "$gt": start_date,
                    "$lt": end_date
                }
            }
        },
        {
            "$group": {
                "_id": "$uniqueKey"
            }
        }
    ]

    cursor = db["userAnalytics"].aggregate(
        pipeline,
        allowDiskUse=True,
        hint="isBot_1_browser_1_country_1_createdDt_1_mapJobId_1"
    )

    count = 0
    for doc in cursor:
        if doc["_id"]:
            local_viewed_keys.add(doc["_id"])
            count += 1

    cursor.close()
    print(f"  [Worker: Views] Finished. Found {count:,} viewed jobs.")
    return local_viewed_keys


def fetch_semrush(uri, db_name, col_name, match_domain):
    """Worker 3: Fetch Semrush whitelist URLs."""
    print(f"  [Worker: Semrush] Started fetching whitelist for domain: {match_domain}...")

    local_semrush_urls = set()

    # Create independent connection for this thread/worker
    client = pymongo.MongoClient(uri)
    db = client[db_name]

    # Updated Query: Checks view_exists AND matches the domain
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
    print("\n========== JOB EXPIRY CHECK (MULTI-THREADED) STARTED ==========\n")
    start_time = time.time()

    # 1. Date Setup
    now = datetime.now(timezone.utc)
    START_DATE = now - timedelta(days=DAYS)
    END_DATE = now

    print(f"Date window: {START_DATE} → {END_DATE}\n")

    # 2. Main DB Connection
    print("Connecting to Main MongoDB...")
    local_client = pymongo.MongoClient(LOCAL_MONGO_URI)
    creds_db = local_client[CREDS_DB]

    creds = creds_db["creds"].find_one({"domain": DOMAIN}, {"mongo_uri": 1})
    if not creds or "mongo_uri" not in creds:
        raise RuntimeError("mongo_uri not found")

    prod_client = pymongo.MongoClient(creds["mongo_uri"])
    prod_db = prod_client[TARGET_DB]

    export_db = local_client[LOCAL_DB]
    export_col = export_db[EXPORT_COLLECTION]
    print("Main connections established.\n")

    # 3. Parallel Execution
    print("Starting parallel workers...")

    jobs = {}
    viewed_keys = set()
    semrush_urls = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit tasks
        future_jobs = executor.submit(fetch_jobs, prod_db, START_DATE, END_DATE)
        future_views = executor.submit(fetch_views, prod_db, START_DATE, END_DATE)
        # Updated to pass the domain filter
        future_semrush = executor.submit(
            fetch_semrush,
            SEMRUSH_MONGO_URI,
            SEMRUSH_DB_NAME,
            SEMRUSH_COLLECTION,
            SEMRUSH_MATCH_DOMAIN
        )

        # Wait for results
        jobs = future_jobs.result()
        viewed_keys = future_views.result()
        semrush_urls = future_semrush.result()

    print("\nAll workers completed.\n")

    if not jobs:
        sys.exit("No jobs found — exiting")

    # 4. Analysis
    print("STEP 4: Calculating jobs to expire...")

    all_keys = set(jobs.keys())
    no_view_keys = all_keys - viewed_keys

    print(f"  • Total Jobs             : {len(all_keys):,}")
    print(f"  • Viewed Jobs            : {len(viewed_keys):,}")
    print(f"  • Initial Zero-View Jobs : {len(no_view_keys):,}")

    final_expiry_docs = []
    semrush_excluded_count = 0

    for k in no_view_keys:
        job = jobs[k]
        job_url = job.get("submittedUrl")

        if job_url and job_url in semrush_urls:
            semrush_excluded_count += 1
            continue

        final_expiry_docs.append(job)

    print(f"  • Excluded (Semrush)     : {semrush_excluded_count:,}")
    print(f"  ✓ Final Jobs to Expire   : {len(final_expiry_docs):,}\n")

    if not final_expiry_docs:
        print("No jobs to expire after filtering.")
    else:
        # 5. Export
        print("STEP 5: Saving final list to local MongoDB...")

        if EXPORT_COLLECTION in export_db.list_collection_names():
            export_db.drop_collection(EXPORT_COLLECTION)
            print(f"  • Dropped existing collection: {EXPORT_COLLECTION}")

        for i in range(0, len(final_expiry_docs), CHUNK_SIZE):
            export_col.insert_many(final_expiry_docs[i:i + CHUNK_SIZE])

        print(f"  ✓ Records written        : {len(final_expiry_docs):,}")
        print(f"  ✓ Target collection     : {LOCAL_DB}.{EXPORT_COLLECTION}")

    elapsed = time.time() - start_time
    print(f"\n========== COMPLETED IN {elapsed:.2f} SECONDS ==========\n")