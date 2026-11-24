import time
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import os
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# CONFIG
# ============================================================
# FIXED: Credentials included for local DB connection
LOCAL_MONGO_URI =  os.getenv("MONGO_URI")
if not LOCAL_MONGO_URI:
    raise Exception("LOCAL_MONGO_URI not found in environment variables") 
SMTP_SENDER = "saidixitn@gmail.com"
SMTP_RECEIVER = "saidixitn@gmail.com"
SMTP_CC = "tarunteja.palla@jobiak.com" # Add your CC here
SMTP_PASSWORD = os.getenv("SMTP_PASS")       # Gmail App Password
if not SMTP_PASSWORD:
    raise Exception("SMTP_PASSWORD not found in environment variables") 

CLIENT_CACHE = {}
CACHE_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print to avoid scrambled worker logs."""
    with PRINT_LOCK:
        print(*args, **kwargs)


# ============================================================
# EMAIL SENDER
# ============================================================
def send_email(html_body: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_SENDER
    msg["To"] = SMTP_RECEIVER
    msg['Cc'] = SMTP_CC  # This displays the CC in the email header
    msg["Subject"] = "Daily Domain Updates Report ⚡"

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SMTP_SENDER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        safe_print("📧 Email Sent Successfully!")
    except Exception as e:
        safe_print("❌ Email sending failed:", e)


# ============================================================
# DB ROUTING
# ============================================================
def pick_db(dtype, domain):
    dtype = (dtype or "").lower()
    clean = domain.split("/")[0].split(".")[0].lower()

    if dtype == "proxy":
        return None, None
    if "sub" in dtype:
        return "directclients_prod", "Target_P4_Opt"
    return f"{clean}_prod", "Target_P4_Opt"


# ============================================================
# REMOTE CONNECTION (CACHED)
# ============================================================
def get_remote(dbname, local):
    if not dbname:
        return None, 0.0

    t0 = time.time()

    # cached connection
    with CACHE_LOCK:
        if dbname in CLIENT_CACHE:
            return CLIENT_CACHE[dbname], round(time.time() - t0, 3)

    # Use the authenticated local connection to fetch creds
    rec = local["mongo_creds"]["creds"].find_one({"domain": dbname})
    if not rec:
        return None, round(time.time() - t0, 3)

    client = MongoClient(rec["mongo_uri"], serverSelectionTimeoutMS=5000)

    try:
        client.admin.command("ping")
        with CACHE_LOCK:
            CLIENT_CACHE[dbname] = client
        return client, round(time.time() - t0, 3)
    except:
        return None, round(time.time() - t0, 3)


# ============================================================
# SLIDING WINDOW AGGREGATION (Fixed Infinite Loop)
# ============================================================
def run_expiring_aggregation(col, utc, quota_left, emp, domain):
    safe_print(f"   🔍 Checking expiring jobs (need {quota_left})...")

    window_start = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    window_days = 10
    
    # Circuit breaker: Limit how far into the future we search (e.g., 90 days)
    MAX_LOOKAHEAD_DAYS = 90
    max_date = window_start + timedelta(days=MAX_LOOKAHEAD_DAYS)

    cumulative = 0
    chosen_day = None
    agg_latency = 0.0

    # Ensure the loop stops if it exceeds max_date
    while cumulative < quota_left and window_start < max_date:

        wnd_end = window_start + timedelta(days=window_days)

        pipeline = [
            {"$match": {
                "pub_expired": {"$gte": window_start, "$lt": wnd_end},
                "gpost": 5,
                "job_status": {"$ne": 3},
                **({"employerId": emp} if emp else {})
            }},
            {"$group": {
                "_id": {
                    "d": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$pub_expired"
                        }
                    }
                },
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id.d": 1}}
        ]

        t0 = time.time()
        try:
            buckets = list(
                col.aggregate(pipeline, allowDiskUse=True, hint="pub_expired_1_gpost_1")
            )
        except Exception as e:
            safe_print(f"❌ Aggregation failed for {domain}: {e}")
            return None, agg_latency

        agg_latency += (time.time() - t0)

        safe_print(f"      → Window {window_start.date()} → {wnd_end.date()} : {len(buckets)} buckets")

        if not buckets:
            window_start = wnd_end
            continue

        # Iterate buckets by date
        for b in buckets:
            day_str = b["_id"]["d"]
            count_for_day = b["count"]

            cumulative += count_for_day

            # Stop at the FIRST DATE where cumulative >= quota_left
            if cumulative >= quota_left:
                chosen_day = day_str
                break

        if chosen_day:
            break

        window_start = wnd_end

    # If the loop maxed out the timeframe without hitting the quota
    if not chosen_day:
        return None, agg_latency

    # Compute next-midnight cutoff (ISODate strictly < cutoff)
    dt = datetime.fromisoformat(chosen_day).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    cutoff_dt = dt + timedelta(days=1)
    cutoff_s = cutoff_dt.strftime("%Y-%m-%dT00:00:00.000+0000")

    return cutoff_s, agg_latency


# ============================================================
# PROCESS DOMAIN
# ============================================================
def process_domain(dom, utc, local):
    dom_start = time.time()
    domain = dom["Domain"]
    dtype = (dom.get("Domain Type") or "").lower()
    quota = dom.get("Quota")
    emp = dom.get("EmployerId")

    safe_print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    safe_print(f"➡️  Starting: {domain}  [{dtype}]")
    safe_print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Proxy?
    if dtype == "proxy":
        safe_print("⚠️ Proxy domain → skipping.")
        return finalize(domain, dtype, quota, 0, 0, "-", "NO UPDATE (proxy)", 0, 0, 0, dom_start, 0, 0)

    if quota is None:
        safe_print("⚠️ Missing quota → skipping.")
        return finalize(domain, dtype, "Missing", 0, 0, "-", "NO UPDATE (missing quota)", 0, 0, 0, dom_start, 0, 0)

    dbname, colname = pick_db(dtype, domain)

    # DB connect
    safe_print("   • Connecting to DB...")
    client, conn_lat = get_remote(dbname, local)
    if not client:
        safe_print("❌ DB connection failed")
        return finalize(domain, dtype, quota, 0, 0, "-", "NO UPDATE (db failed)", conn_lat, 0, 0, dom_start, 0, 0)

    col = client[dbname][colname]

    # Posted
    day_start = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    q_post = {"job_status": {"$ne": 3}, "gpost": 5, "gpost_date": {"$gte": day_start}}
    if emp:
        q_post["employerId"] = emp

    t = time.time()
    posted = col.count_documents(q_post)
    posted_lat = time.time() - t

    # Queue
    q_queue = {"job_status": {"$ne": 3}, "gpost": 3}
    if emp:
        q_queue["employerId"] = emp

    t = time.time()
    queue = col.count_documents(q_queue)
    queue_lat = time.time() - t

    safe_print(f"      Posted: {posted} | Queue: {queue}")

    if posted + queue >= quota:
        safe_print("⚠️ Quota Full → Skipping aggregation")
        return finalize(domain, dtype, quota, posted, queue, "-", "NO UPDATE (quota full)", conn_lat, posted_lat,
                        queue_lat, dom_start, 0, 0)

    quota_left = quota - (posted + queue)
    safe_print(f"      Quota Remaining: {quota_left}")

    # Aggregation
    cutoff, agg_lat = run_expiring_aggregation(col, utc, quota_left, emp, domain)

    if not cutoff:
        safe_print("⚠️ No future expiring jobs.")
        return finalize(domain, dtype, quota, posted, queue, "-", "NO UPDATE (no future jobs)", conn_lat, posted_lat,
                        queue_lat, dom_start, agg_lat, 0)

    # Count of Jobs matching the query (pub_expired < cutoff)
    query_filter = {"pub_expired": {"$lt": datetime.fromisoformat(cutoff)}, "gpost": 5, "job_status": {"$ne": 3}}
    if emp:
        query_filter["employerId"] = emp

    job_count = col.count_documents(query_filter)

    # -----------------------------------------------------------------
    # QUERY CONSTRUCTION
    # -----------------------------------------------------------------
    final_query = (
        f'{{ "pub_expired": {{ $lt: ISODate("{cutoff}") }}, '
        f'"gpost": NumberInt(5), "job_status": {{ $ne: NumberInt(3) }}'
    )
    if emp:
        final_query += f', "employerId": "{emp}"'
    final_query += " }"
    # -----------------------------------------------------------------

    safe_print(f"✔️ Completed {domain} in {round(time.time() - dom_start, 3)}s")

    return finalize(domain, dtype, quota, posted, queue, cutoff, final_query,
                    conn_lat, posted_lat, queue_lat, dom_start, agg_lat, job_count)


# ============================================================
# FINALIZE RESULT DICT
# ============================================================
def finalize(domain, dtype, quota, posted, queue, cutoff_date,
             query, conn_lat, post_lat, queue_lat, dom_start, agg_lat, job_count):
    return {
        "Domain": domain,
        "Type": dtype,
        "Quota": quota,
        "Posted": posted,
        "Queue": queue,
        "CutoffDate": cutoff_date,
        "JobCount": job_count,
        "Query": query,
        "Conn": round(conn_lat, 3),
        "Post": round(post_lat, 3),
        "QueueLat": round(queue_lat, 3),
        "Agg": round(agg_lat, 3),
        "Total": round(time.time() - dom_start, 3)
    }


# ============================================================
# SAFE WRAPPER
# ============================================================
def process_domain_safe(dom, utc, local):
    try:
        return process_domain(dom, utc, local)
    except Exception as e:
        safe_print(f"❌ ERROR in {dom.get('Domain')}: {e}")
        return finalize(
            dom.get("Domain"),
            dom.get("Domain Type"),
            dom.get("Quota"),
            "-",
            "-",
            "-",
            f"ERROR: {e}",
            0,
            0,
            0,
            time.time(),
            0,
            0
        )


# ============================================================
# MAIN
# ============================================================
def main():
    script_start = time.time()
    safe_print("🔥 SCRIPT STARTED")

    # Connect using the URI that contains credentials
    local = MongoClient(LOCAL_MONGO_URI)

    try:
        # Test connection by listing domains
        domains = list(local["domain_postings"]["domains"].find({}, {"_id": 0}))
        safe_print(f"📦 Loaded {len(domains)} domains")
    except Exception as e:
        safe_print(f"❌ CRITICAL ERROR: Could not connect to local DB. {e}")
        return

    utc = datetime.now(timezone.utc)

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(process_domain_safe, d, utc, local) for d in domains]

        for f in as_completed(futures):
            results.append(f.result())

    # Email Cards HTML
    domain_cards_html = ""
    update_count = 0

    for r in results:
        # Exclude proxy domains
        if r["Type"] == "proxy":
            continue

        needs_update = not r["Query"].startswith(("NO UPDATE", "ERROR"))
        if needs_update:
            update_count += 1

        # Progress ratio
        posted = r["Posted"] if isinstance(r["Posted"], int) else 0
        queue = r["Queue"] if isinstance(r["Queue"], int) else 0
        quota = r["Quota"] if isinstance(r["Quota"], int) else 1

        # Display Progress Bar
        posted_pct = min(100, round((posted / quota) * 100, 2)) if quota else 0
        queue_pct = min(100, round((queue / quota) * 100, 2)) if quota else 0

        # Domain Card
        domain_cards_html += f"""
        <div style="
            padding:26px; margin-bottom:28px; border-radius:22px;
            background:#ffffff;
            border:1px solid #e4e6ef;
            box-shadow:0 6px 20px rgba(99,102,241,0.12);
            font-family:'Inter',sans-serif;"> 

            <h3 style="
                margin:0 0 10px 0; font-size:20px; color:#4f46e5; 
                font-weight:600; letter-spacing:-0.25px;">
                {r['Domain']}
            </h3>

            <div style="margin-top:4px; color:#374151; font-size:15px; line-height:1.62;">
                <b>Posted:</b> {r['Posted']} &nbsp;&nbsp;
                <b>Queue:</b> {r['Queue']}<br>
                <b>Quota:</b> {r['Quota']}<br>
                <b>Cutoff Date:</b> {r['CutoffDate']}<br>
                <b>Job Count:</b> {r['JobCount']}
            </div>

            <div style="margin-top:14px;">
              <div style="font-size:13px; color:#4b5563; margin-bottom:6px;">
                Posted Progress: {r['Posted']} / {r['Quota']}
              </div>
              <div style="width:100%; height:10px; background:#e5e7eb; border-radius:10px;">
                <div style="height:10px; width:{posted_pct}%; background:#6366f1; border-radius:10px;"></div>
              </div>
              <div style="font-size:13px; color:#4b5563; margin-top:6px; margin-bottom:6px;">
                Queue Progress: {r['Queue']} / {r['Quota']}
              </div>
              <div style="width:100%; height:10px; background:#e5e7eb; border-radius:10px;">
                <div style="height:10px; width:{queue_pct}%; background:#34d399; border-radius:10px;"></div>
              </div>
            </div>

            <pre style="
                background:#fafbff; padding:16px 20px; margin-top:22px;
                border-radius:14px; font-size:13px; 
                line-height:1.55; color:#1f2937;
                white-space:pre-wrap; border:1px solid #e2e7ff;">
{r['Query']}
            </pre>

            <div style="margin-top:22px; font-size:15px; line-height:1.62;">
                <b>Latency Breakdown:</b><br>
                DB Connect: <span style="color:#16a34a;">{r['Conn']}s</span><br>
                Posted Query: <span style="color:#16a34a;">{r['Post']}s</span><br>
                Queue Query: <span style="color:#16a34a;">{r['QueueLat']}s</span><br>
                Aggregation: <span style="color:#f97316;">{r['Agg']}s</span><br>
                Total Time: <span style="color:#dc2626; font-weight:700;">{r['Total']}s</span>
            </div>

        </div>
        """

    # Final Email HTML
    total_runtime = round(time.time() - script_start, 2)

    html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0; padding:0; background:#eef1ff;
             font-family:'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"> 

<div style="padding:40px;">

  <div style="max-width:780px; margin:0 auto;
              background:linear-gradient(145deg,#ffffff,#f5f7ff);
              padding:42px; border-radius:26px;
              box-shadow:0 14px 34px rgba(80,80,200,0.15);">

    <h2 style="margin:0; font-size:30px; font-weight:700; 
               color:#4338ca; letter-spacing:-0.4px;">
      Daily Domain Updates Report ⚡
    </h2>

    <p style="margin:8px 0 28px 0; color:#6b7280; 
              font-size:15px; line-height:1.52;">
      Generated using dynamic quota analysis and expiring job projections.
    </p>

    <div style="background:linear-gradient(135deg,#e4e7ff,#d8dcff);
                padding:22px 26px; border-radius:20px;
                border-left:6px solid #6366f1; 
                margin-bottom:34px;"> 

      <div style="font-size:15px; color:#374151; line-height:1.62;">
        <b style="color:#111827;">⏱ Total Runtime:</b> {total_runtime}s<br>
        <b style="color:#111827;">📦 Total Domains:</b> {len(domains)}<br>
        <b style="color:#111827;">🔁 Domains Updated:</b> {update_count}
      </div>

    </div>

    {domain_cards_html}

    <div style="margin-top:40px; text-align:center; color:#9ca3af;
                font-size:13px;">
      Generated automatically · Domain Updates Report
    </div>

  </div>
</div>

</body>
</html>
"""

    send_email(html)


# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    main()