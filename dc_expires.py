import sys
import time
import pymongo
import concurrent.futures
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
load_dotenv()
# =========================================================
# CONFIG
# =========================================================

LOCAL_MONGO_URI =  os.getenv("MONGO_URI")

CREDS_DB = "mongo_creds"

# ---------------------------------------------------------
# SOURCE DATABASE
# ---------------------------------------------------------

DOMAIN = "directclients_prod"
TARGET_DB = DOMAIN

# ---------------------------------------------------------
# LOCAL EXPORT DATABASE
# ---------------------------------------------------------

LOCAL_DB = "domain_expires"

# ---------------------------------------------------------
# COLLECTION WITH URLS TO SKIP
# ---------------------------------------------------------

SEMRUSH_COLLECTION = "semrush_url's"

# ---------------------------------------------------------
# EMPLOYER → EXPORT COLLECTION MAP
# ---------------------------------------------------------

ID_MAP = {
    "emp-jbk-apexfocusgroup": "apexfocusgroup_expires",
    # "emp-jbk-newearnhaus": "newearnhaus_expires",
    "emp-jbk-levelsurveys": "levelsurveys_expires"
}

# ---------------------------------------------------------
# PERFORMANCE
# ---------------------------------------------------------

DAYS = 30
MAX_WORKERS = 10
CHUNK_SIZE = 10_000

# =========================================================
# HELPERS
# =========================================================

def chunked(data, size):
    """
    Yield chunks from list.
    """

    for i in range(0, len(data), size):
        yield data[i:i + size]


# =========================================================
# FETCH ACTIVE JOBS
# =========================================================

def fetch_jobs(db, start_date, end_date):

    print("  [Jobs] Fetching active jobs...")

    employer_ids = list(ID_MAP.keys())

    jobs = {}

    pipeline = [
        {
            "$match": {
                "employerId": {
                    "$in": employer_ids
                },
                "job_status": {
                    "$ne": "3.0"
                },
                "gpost": 5.0,
                "gpost_date": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "submittedUrl": {
                    "$exists": True,
                    "$ne": None
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

    cursor = db["Target_P4_Opt"].aggregate(
        pipeline,
        allowDiskUse=True,
        batchSize=5000
    )

    total = 0

    for doc in cursor:

        url = doc.get("submittedUrl")

        if not url:
            continue

        jobs[url] = doc
        total += 1

    cursor.close()

    print(f"  [Jobs] Loaded {total:,} jobs.")

    return jobs


# =========================================================
# FETCH VIEWED URLS
# =========================================================

def fetch_viewed_urls(db, start_date, end_date):

    print("  [Views] Fetching viewed URLs...")

    viewed_urls = set()

    pipeline = [
        {
            "$match": {
                "isBot": False,
                "browserType": {
                    "$ne": "Unknown"
                },
                "deviceType": {
                    "$ne": "Unknown"
                },
                "isFromGoogle": True,
                "submittedUrl": {
                    "$exists": True,
                    "$ne": None
                },
                "createdDt": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
        },
        {
            "$group": {
                "_id": "$submittedUrl"
            }
        }
    ]

    cursor = db["userAnalytics"].aggregate(
        pipeline,
        allowDiskUse=True,
        batchSize=10000
    )

    total = 0

    for doc in cursor:

        url = doc.get("_id")

        if not url:
            continue

        viewed_urls.add(url)
        total += 1

    cursor.close()

    print(f"  [Views] Loaded {total:,} viewed URLs.")

    return viewed_urls


# =========================================================
# FETCH SEMRUSH URLS
# =========================================================

def fetch_semrush_urls(export_db):

    print(f"  [Semrush] Loading skip URLs from {SEMRUSH_COLLECTION}...")

    semrush_urls = set()

    cursor = export_db[SEMRUSH_COLLECTION].find(
        {
            "url": {
                "$exists": True,
                "$ne": None
            }
        },
        {
            "_id": 0,
            "url": 1
        },
        batch_size=10000
    )

    total = 0

    for doc in cursor:

        url = doc.get("url")

        if not url:
            continue

        semrush_urls.add(url)
        total += 1

    cursor.close()

    print(f"  [Semrush] Loaded {total:,} skip URLs.")

    return semrush_urls


# =========================================================
# WRITE EXPORT COLLECTION
# =========================================================

def write_collection(collection, docs):

    collection.drop()

    if not docs:
        return 0

    inserted = 0

    for chunk in chunked(docs, CHUNK_SIZE):

        try:

            collection.insert_many(
                chunk,
                ordered=False
            )

            inserted += len(chunk)

        except BulkWriteError as e:

            inserted += len(
                e.details.get("writeErrors", [])
            )

    return inserted


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("\n" + "=" * 70)
    print("STARTING DOMAIN EXPIRES EXPORT")
    print("=" * 70 + "\n")

    start_time = time.time()

    # =====================================================
    # DATE RANGE
    # =====================================================

    now = datetime.now(timezone.utc)

    START_DATE = now - timedelta(days=DAYS)
    END_DATE = now

    # =====================================================
    # CONNECTIONS
    # =====================================================

    print("[Mongo] Connecting...")

    local_client = MongoClient(
        LOCAL_MONGO_URI,
        maxPoolSize=100
    )

    creds_db = local_client[CREDS_DB]

    creds = creds_db["creds"].find_one(
        {
            "domain": DOMAIN
        },
        {
            "mongo_uri": 1
        }
    )

    if not creds:

        sys.exit(
            f"\nERROR: Credentials not found for domain: {DOMAIN}\n"
        )

    prod_client = MongoClient(
        creds["mongo_uri"],
        maxPoolSize=100
    )

    prod_db = prod_client[TARGET_DB]

    export_db = local_client[LOCAL_DB]

    print("[Mongo] Connected.\n")

    # =====================================================
    # PARALLEL FETCH
    # =====================================================

    print(f"[Executor] Running with {MAX_WORKERS} workers...\n")

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_jobs = executor.submit(
            fetch_jobs,
            prod_db,
            START_DATE,
            END_DATE
        )

        future_views = executor.submit(
            fetch_viewed_urls,
            prod_db,
            START_DATE,
            END_DATE
        )

        future_semrush = executor.submit(
            fetch_semrush_urls,
            export_db
        )

        jobs_dict = future_jobs.result()

        viewed_urls = future_views.result()

        semrush_urls = future_semrush.result()

    # =====================================================
    # FILTERING
    # =====================================================

    print("\n" + "=" * 70)
    print("FILTERING")
    print("=" * 70)

    all_urls = set(jobs_dict.keys())

    print(f"\nTotal Jobs                : {len(all_urls):,}")

    # -----------------------------------------------------
    # REMOVE VIEWED URLS
    # -----------------------------------------------------

    non_viewed_urls = all_urls - viewed_urls

    removed_views = len(all_urls) - len(non_viewed_urls)

    print(f"Viewed URLs Removed       : {removed_views:,}")

    # -----------------------------------------------------
    # REMOVE SEMRUSH URLS
    # -----------------------------------------------------

    final_urls = non_viewed_urls - semrush_urls

    removed_semrush = len(non_viewed_urls) - len(final_urls)

    print(f"Semrush URLs Removed      : {removed_semrush:,}")

    print(f"Final Export URLs         : {len(final_urls):,}")

    # =====================================================
    # BUILD EXPORT BUCKETS
    # =====================================================

    print("\n" + "=" * 70)
    print("BUILDING EXPORT COLLECTIONS")
    print("=" * 70)

    export_buckets = {
        collection_name: []
        for collection_name in ID_MAP.values()
    }

    for url in final_urls:

        job_doc = jobs_dict.get(url)

        if not job_doc:
            continue

        employer_id = job_doc.get("employerId")

        target_collection = ID_MAP.get(employer_id)

        if not target_collection:
            continue

        export_buckets[target_collection].append(job_doc)

    # =====================================================
    # WRITE EXPORTS
    # =====================================================

    print("\n" + "=" * 70)
    print("WRITING EXPORTS")
    print("=" * 70 + "\n")

    total_written = 0

    for collection_name, docs in export_buckets.items():

        print(f"[Writing] {collection_name}")

        inserted = write_collection(
            export_db[collection_name],
            docs
        )

        total_written += inserted

        print(f"  → Inserted {inserted:,} documents.\n")

    # =====================================================
    # FINAL STATS
    # =====================================================

    elapsed = time.time() - start_time

    print("=" * 70)
    print("COMPLETED")
    print("=" * 70)

    print(f"\nTotal Exported Documents  : {total_written:,}")
    print(f"Execution Time            : {elapsed:.2f} sec\n")