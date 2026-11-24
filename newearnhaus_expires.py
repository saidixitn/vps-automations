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

# Source Database
DOMAIN = "directclients_prod"
TARGET_DB = DOMAIN

# Local Export DB
LOCAL_DB = "domain_expires"

# Employer ID Mapping
ID_MAP = {
    #"emp-jbk-apexfocusgroup": "apexfocusgroup_expires",
    "emp-jbk-newearnhaus": "newearnhaus_expires",
    #"emp-jbk-levelsurveys": "levelsurveys_expires"
}

DAYS = 30
CHUNK_SIZE = 10_000
MAX_WORKERS = 10


# --------------------------------------------------
# WORKER FUNCTIONS
# --------------------------------------------------

def fetch_jobs(db, start_date, end_date):
    """Worker: Fetch active jobs for targeted employer IDs."""
    print("  [Worker: Jobs] Querying Target_P4_Opt...")

    local_jobs = {}
    employer_ids = list(ID_MAP.keys())

    pipeline = [
        {
            "$match": {
                "employerId": {"$in": employer_ids},
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
                "company": 1,
                "jobtitle": 1,
                "gpost_date": 1,
                "employerId": 1,
                "pub_expired": 1,
                "submittedUrl": 1
            }
        }
    ]

    cursor = db["Target_P4_Opt"].aggregate(pipeline, allowDiskUse=True)

    count = 0
    for doc in cursor:
        url = doc.get("submittedUrl")
        if url:
            local_jobs[url] = doc
            count += 1

    cursor.close()
    print(f"  [Worker: Jobs] Finished. Found {count:,} jobs.")
    return local_jobs


def fetch_views(db, start_date, end_date):
    """Worker: Fetch viewed submittedUrls from analytics."""
    print("  [Worker: Views] Querying userAnalytics...")

    local_viewed_urls = set()
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
                "_id": "$submittedUrl"
            }
        }
    ]

    # Note: Ensure an index exists on submittedUrl and createdDt for performance
    cursor = db["userAnalytics"].aggregate(pipeline, allowDiskUse=True)

    count = 0
    for doc in cursor:
        if doc["_id"]:
            local_viewed_urls.add(doc["_id"])
            count += 1

    cursor.close()
    print(f"  [Worker: Views] Finished. Found {count:,} unique viewed URLs.")
    return local_viewed_urls


# --------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------
if __name__ == "__main__":
    print("\n========== DUAL-EMPLOYER EXPIRY SYNC STARTING ==========\n")
    start_time = time.time()

    # 1. Date Setup
    now = datetime.now(timezone.utc)
    START_DATE = now - timedelta(days=DAYS)
    END_DATE = now

    # 2. Connections
    local_client = pymongo.MongoClient(LOCAL_MONGO_URI)
    creds_db = local_client[CREDS_DB]

    creds = creds_db["creds"].find_one({"domain": DOMAIN}, {"mongo_uri": 1})
    if not creds:
        sys.exit(f"Error: Credentials for '{DOMAIN}' not found in {CREDS_DB}.creds")

    prod_client = pymongo.MongoClient(creds["mongo_uri"])
    prod_db = prod_client[TARGET_DB]
    export_db = local_client[LOCAL_DB]

    # 3. Parallel Execution
    print(f"Executing with {MAX_WORKERS} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_jobs = executor.submit(fetch_jobs, prod_db, START_DATE, END_DATE)
        future_views = executor.submit(fetch_views, prod_db, START_DATE, END_DATE)

        jobs_dict = future_jobs.result()
        viewed_urls = future_views.result()

    # 4. Filter Logic
    all_urls = set(jobs_dict.keys())
    no_view_urls = all_urls - viewed_urls

    # Initialize storage for split results
    export_buckets = {coll_name: [] for coll_name in ID_MAP.values()}

    for url in no_view_urls:
        job_doc = jobs_dict[url]
        emp_id = job_doc.get("employerId")

        if emp_id in ID_MAP:
            target_collection = ID_MAP[emp_id]
            export_buckets[target_collection].append(job_doc)

    # 5. Export and Cleanup
    print("\nSTEP 5: Writing to Local Collections...")
    for coll_name, docs in export_buckets.items():
        # Drop existing collection to ensure a fresh list
        export_db[coll_name].drop()

        if not docs:
            print(f"  • {coll_name}: 0 expired jobs found.")
            continue

        # Batch insert for efficiency
        for i in range(0, len(docs), CHUNK_SIZE):
            export_db[coll_name].insert_many(docs[i:i + CHUNK_SIZE])

        print(f"  ✓ {coll_name}: Written {len(docs):,} records.")

    elapsed = time.time() - start_time
    print(f"\n========== COMPLETED IN {elapsed:.2f} SECONDS ==========\n")