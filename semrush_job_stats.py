import pymongo
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sys
import os
from dotenv import load_dotenv
load_dotenv()
# ==================================================
# CONFIG
# ==================================================
LOCAL_MONGO_URI = os.getenv("MONGO_URI")
CREDS_DB = "mongo_creds"

DOMAINS = [
    "v2valuejobs_prod",
    "justopinionjobs_prod",
]

LOCAL_DB = "domain_expires"
STATS_COLLECTION = "job_semrush_daily_stats"
LOG_COLLECTION = "job_semrush_logs"

DAYS = 30
# ==================================================

now = datetime.now(timezone.utc)
START_DATE = now - timedelta(days=DAYS)
END_DATE = now
RUN_DATE = now.strftime("%Y-%m-%d")

print("\n========== SEMRUSH JOB ANALYTICS START ==========\n")
print(f"Date Window : {START_DATE} → {END_DATE}")
print(f"Run Date   : {RUN_DATE}\n")

# ==================================================
# CONNECT TO LOCAL MONGO
# ==================================================
local_client = pymongo.MongoClient(LOCAL_MONGO_URI)
creds_db = local_client[CREDS_DB]
analytics_db = local_client[LOCAL_DB]

stats_col = analytics_db[STATS_COLLECTION]
logs_col = analytics_db[LOG_COLLECTION]

# ==================================================
# MAIN LOOP
# ==================================================
for DOMAIN in DOMAINS:
    print(f"\n---- Processing domain: {DOMAIN} ----")

    creds = creds_db["creds"].find_one({"domain": DOMAIN}, {"mongo_uri": 1})
    if not creds:
        print(f"  ✗ Mongo URI missing for {DOMAIN}")
        continue

    prod_client = pymongo.MongoClient(creds["mongo_uri"])
    prod_db = prod_client[DOMAIN]

    # ----------------------------------------------
    # STEP 1: FETCH VALID JOBS
    # ----------------------------------------------
    jobs = {}

    job_pipeline = [
        {
            "$match": {
                "job_status": {"$ne": 3},              # ✅ numeric
                "gpost": {"$gte": 5},                  # ✅ include all Google posts
                "gpost_date": {"$gt": START_DATE, "$lt": END_DATE},
                "submittedUrl": {"$exists": True, "$nin": ["", None]},
                "uniqueKey": {"$exists": True, "$ne": None},
            }
        },
        {
            "$project": {
                "_id": 0,
                "uniqueKey": 1,
                "company": 1,
                "jobtitle": 1,
                "submittedUrl": 1,
            }
        },
    ]

    for doc in prod_db["Target_P4_Opt"].aggregate(job_pipeline, allowDiskUse=True):
        jobs[doc["uniqueKey"]] = doc

    total_jobs = len(jobs)
    print(f"  ✓ Jobs fetched          : {total_jobs:,}")

    if not jobs:
        continue

    # ----------------------------------------------
    # STEP 2: FETCH CLICKED JOB KEYS
    # ----------------------------------------------
    clicked_jobs = set()

    clicks_pipeline = [
        {
            "$match": {
                "isBot": False,
                "isFromGoogle": True,
                "createdDt": {"$gt": START_DATE, "$lt": END_DATE},
                "uniqueKey": {"$exists": True, "$ne": None},
            }
        },
        {
            "$group": {"_id": "$uniqueKey"}
        },
    ]

    for doc in prod_db["userAnalytics"].aggregate(clicks_pipeline, allowDiskUse=True):
        clicked_jobs.add(doc["_id"])

    print(f"  ✓ Jobs with ≥1 click    : {len(clicked_jobs):,}")

    # ----------------------------------------------
    # STEP 3: CLASSIFICATION
    # ----------------------------------------------
    stats = defaultdict(int)

    for key in jobs:
        stats["total_jobs"] += 1

        if key in clicked_jobs:
            stats["jobs_with_clicks"] += 1
        else:
            stats["jobs_zero_clicks"] += 1

    # ----------------------------------------------
    # STEP 4: SAVE STATS
    # ----------------------------------------------
    stats_doc = {
        "run_date": RUN_DATE,
        "domain": DOMAIN,
        "date_window_start": START_DATE,
        "date_window_end": END_DATE,
        "total_jobs": stats["total_jobs"],
        "jobs_with_clicks": stats["jobs_with_clicks"],
        "jobs_zero_clicks": stats["jobs_zero_clicks"],
        "created_at": now,
    }

    stats_col.update_one(
        {"run_date": RUN_DATE, "domain": DOMAIN},
        {"$set": stats_doc},
        upsert=True,
    )

    print(f"  ✓ Jobs total            : {stats['total_jobs']:,}")
    print(f"  ✓ Jobs with clicks      : {stats['jobs_with_clicks']:,}")
    print(f"  ✓ Jobs zero clicks      : {stats['jobs_zero_clicks']:,}")

print("\n========== SEMRUSH JOB ANALYTICS COMPLETED ==========\n")
