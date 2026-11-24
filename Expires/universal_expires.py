import os
import sys
import time
import schedule
import pymongo
import concurrent.futures
from datetime import datetime, timedelta, timezone

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
LOCAL_URI = os.getenv("MONGO_URI")
CREDS_DB = "mongo_creds"
DOMAINS_DB = "domain_expires"
DOMAINS_COL = "domains"

# Semrush (Programmatic Only)
SEMRUSH_DB = "domain_expires"
SEMRUSH_COL = "semrush_url's"

DAYS = 30
MAX_WORKERS_PER_DOMAIN = 3

# --------------------------------------------------
# HELPER: Database & Collection Resolver
# --------------------------------------------------
def resolve_config(doc):
    """
    Normalizes the config document to determine DB Name, Domain URL, etc.
    Handles both 'v2valuejobs_prod' (db name) and 'v2valuejobs.com' (url) styles.
    """
    raw_domain = doc.get("domain") or doc.get("Domain")
    
    # 1. Determine Target DB Name
    # If it looks like a URL (has .com), split it. If it looks like a DB name, use it.
    if "." in raw_domain:
        prefix = raw_domain.split('.')[0]
        target_db = f"{prefix}_prod"
    else:
        target_db = raw_domain # It's already the db name (e.g. v2valuejobs_prod)

    # 2. Determine Export Collection
    if "apexfocusgroup" in target_db:
        export_col = "apexfocusgroup_expires"
    elif "levelsurveys" in target_db:
        export_col = "levelsurveys_expires"
    else:
        export_col = f"{target_db}_expires"

    # 3. Determine Semrush Domain
    # Use explicit field if exists, otherwise assume raw_domain is the URL
    semrush_dom = doc.get("semrush_domain") or doc.get("semrush_domain")
    if not semrush_dom and "." in raw_domain:
        semrush_dom = raw_domain

    return target_db, export_col, semrush_dom

# --------------------------------------------------
# WORKER FUNCTIONS
# --------------------------------------------------
def fetch_jobs_programmatic(db, start_date, end_date):
    """Fetch ALL jobs (Target_P4_Opt)."""
    print("    [Query] Strategy: Programmatic (Global Fetch)")
    jobs = {}
    pipeline = [
        {"$match": {
            "employerId": {"$exists": True},
            "job_status": {"$ne": "3.0"},
            "gpost": 5.0,
            "gpost_date": {"$gt": start_date, "$lt": end_date}
        }},
        {"$project": {
            "_id": 0, "uniqueKey": 1, "company": 1, "jobtitle": 1, 
            "gpost_date": 1, "employerId": 1, "pub_expired": 1, "submittedUrl": 1
        }}
    ]
    cursor = db["Target_P4_Opt"].aggregate(pipeline, allowDiskUse=True)
    for doc in cursor:
        if "uniqueKey" in doc: jobs[doc["uniqueKey"]] = doc
    return jobs

def fetch_jobs_by_employer(db, start_date, end_date, employer_id):
    """Fetch jobs by EmployerId."""
    print(f"    [Query] Strategy: EmployerId ({employer_id})")
    jobs = {}
    
    col_name = "Target_P4_Opt"
    if col_name not in db.list_collection_names():
        col_name = "job" # Fallback for some DBs

    query_match = {
        "employerId": employer_id,
        "job_status": {"$ne": "3.0"},
        "gpost": 5.0,
        "gpost_date": {"$gt": start_date, "$lt": end_date}
    }

    if col_name == "job":
        # Earnhaus style (simple find)
        cursor = db[col_name].find({"employerId": employer_id, "status": "posted"}, 
                                 {"_id":0, "jobId":1, "submittedUrl":1, "company":1, "jobtitle":1})
        for doc in cursor:
            jid = doc.get("jobId")
            if jid:
                doc["uniqueKey"] = jid
                jobs[jid] = doc
    else:
        # Standard Aggregate
        pipeline = [
            {"$match": query_match},
            {"$project": {
                "_id": 0, "uniqueKey": 1, "company": 1, "jobtitle": 1, 
                "gpost_date": 1, "employerId": 1, "pub_expired": 1, "submittedUrl": 1
            }}
        ]
        cursor = db[col_name].aggregate(pipeline, allowDiskUse=True)
        for doc in cursor:
            if "uniqueKey" in doc: jobs[doc["uniqueKey"]] = doc
            
    return jobs

def fetch_views(db, start_date, end_date, employer_id=None):
    """Fetch User Views."""
    viewed = set()
    match_stage = {
        "isBot": False, "browserType": {"$ne": "Unknown"}, 
        "deviceType": {"$ne": "Unknown"}, "isFromGoogle": True, 
        "createdDt": {"$gt": start_date, "$lt": end_date}
    }
    if employer_id: match_stage["employerId"] = employer_id

    cursor = db["userAnalytics"].find(match_stage, {"uniqueKey": 1, "jobId": 1})
    for doc in cursor:
        val = doc.get("uniqueKey") or doc.get("jobId")
        if val: viewed.add(val)
    return viewed

def fetch_semrush(db, match_domain):
    """Fetch Semrush Whitelist."""
    urls = set()
    if not match_domain: return urls
    
    query = {"view_exists": {"$exists": False}, "domain": match_domain}
    cursor = db[SEMRUSH_COL].find(query, {"url": 1})
    for doc in cursor:
        if "url" in doc: urls.add(doc["url"])
    return urls

# --------------------------------------------------
# CORE PROCESSOR
# --------------------------------------------------
def process_domain_job(config_doc):
    local_client = pymongo.MongoClient(LOCAL_URI)
    
    # 1. Resolve Config
    raw_domain = config_doc.get("domain") or config_doc.get("Domain")
    d_type = (config_doc.get("type") or config_doc.get("Domain Type") or "programmatic").lower()
    employer_id = config_doc.get("employerId") or config_doc.get("EmployerId")
    
    target_db_name, export_col_name, semrush_dom = resolve_config(config_doc)
    
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] STARTING: {raw_domain}")
    print(f"    DB: {target_db_name} | Type: {d_type} | Semrush: {semrush_dom}")

    # 2. Get Credentials
    creds_db = local_client[CREDS_DB]
    # Try finding by 'domain' field (e.g. v2valuejobs_prod)
    creds = creds_db["creds"].find_one({"domain": raw_domain}, {"mongo_uri": 1})
    if not creds:
        # Fallback: try resolved DB name
        creds = creds_db["creds"].find_one({"domain": target_db_name}, {"mongo_uri": 1})

    if not creds:
        print(f"    [Error] No Credentials found for {raw_domain}. Skipping.")
        local_client.close()
        return

    # 3. Connect
    try:
        prod_client = pymongo.MongoClient(creds["mongo_uri"])
        prod_db = prod_client[target_db_name]
    except Exception as e:
        print(f"    [Error] Connection Failed: {e}")
        local_client.close()
        return

    # 4. Dates
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=DAYS)
    end_dt = now

    # 5. Execute Workers
    jobs = {}
    views = set()
    semrush_urls = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_PER_DOMAIN) as ex:
        # Jobs
        if "programmatic" in d_type:
            f_jobs = ex.submit(fetch_jobs_programmatic, prod_db, start_dt, end_dt)
            f_sem = ex.submit(fetch_semrush, local_client[SEMRUSH_DB], semrush_dom)
        else:
            if not employer_id:
                print("    [Error] Proxy type requires employerId.")
                local_client.close()
                return
            f_jobs = ex.submit(fetch_jobs_by_employer, prod_db, start_dt, end_dt, employer_id)
            f_sem = None

        # Views
        f_views = ex.submit(fetch_views, prod_db, start_dt, end_dt, employer_id if "programmatic" not in d_type else None)

        jobs = f_jobs.result()
        views = f_views.result()
        if f_sem:
            semrush_urls = f_sem.result()
            print(f"    [Semrush] Found {len(semrush_urls):,} whitelist URLs")

    # 6. Filter
    all_keys = set(jobs.keys())
    no_view_keys = all_keys - views
    final_docs = []
    
    for k in no_view_keys:
        job = jobs[k]
        url = job.get("submittedUrl")
        if url and url in semrush_urls:
            continue
        final_docs.append(job)

    print(f"    [Result] Total: {len(all_keys):,} | Expiring: {len(final_docs):,}")

    # 7. Export
    if final_docs:
        export_db = local_client[DOMAINS_DB]
        col = export_db[export_col_name]
        col.drop() # Clean start
        
        chunk_size = 5000
        for i in range(0, len(final_docs), chunk_size):
            col.insert_many(final_docs[i:i+chunk_size])
        print(f"    [Success] Saved to {export_col_name}")

    local_client.close()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] COMPLETED: {raw_domain}\n")


# --------------------------------------------------
# SCHEDULER SETUP
# --------------------------------------------------
def reload_schedules():
    """Loads all active domains from DB and schedules them."""
    schedule.clear()
    
    try:
        local_client = pymongo.MongoClient(LOCAL_URI)
        domains_col = local_client[DOMAINS_DB][DOMAINS_COL]
        
        # Only fetch active domains
        domains = list(domains_col.find({"active": True}))
        local_client.close()
        
        print(f"\n>>> LOADING SCHEDULES ({len(domains)} active domains found)")
        
        for config in domains:
            domain_name = config.get("domain") or config.get("Domain")
            run_time = config.get("cron_time")
            
            if domain_name and run_time:
                # Schedule the job dynamically
                schedule.every().day.at(run_time).do(process_domain_job, config_doc=config)
                print(f"    ✓ Scheduled {domain_name} at {run_time}")
            else:
                print(f"    x Skipped {domain_name} (Missing cron_time or name)")
                
    except Exception as e:
        print(f"SCHEDULER ERROR: {e}")

if __name__ == "__main__":
    print("SYSTEM STARTUP: Universal Scheduler")
    
    # 1. Print Server Time so you can debug offsets
    server_time = datetime.now().strftime("%H:%M")
    print(f"CURRENT SERVER TIME: {server_time}")
    if datetime.now().hour != datetime.utcnow().hour:
        print("NOTE: Server appears to be using Local Time (not UTC). Ensure cron_time matches this.")
    else:
        print("NOTE: Server appears to be using UTC. Ensure cron_time is in UTC.")

    # 2. Load Jobs
    reload_schedules()
    
    # 3. Optional: Refresh schedule every hour to pick up DB changes
    schedule.every().hour.do(reload_schedules)

    # 4. Loop
    while True:
        schedule.run_pending()
        time.sleep(1)