import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# CONFIG
# ============================================================
LOCAL_MONGO_URI =  os.getenv("MONGO_URI")
if not LOCAL_MONGO_URI:
    raise Exception("LOCAL_MONGO_URI not found in environment variables") 
SMTP_SENDER = "saidixitn@gmail.com"
SMTP_RECEIVER = "saidixitn@gmail.com"
SMTP_CC = "tarunteja.palla@jobiak.com"
SMTP_PASSWORD = os.getenv("SMTP_PASS")       # Gmail App Password
if not SMTP_PASSWORD:
    raise Exception("SMTP_PASSWORD not found in environment variables") 

CLIENT_CACHE = {}
CACHE_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()


def safe_print(*args, **kwargs):
    with PRINT_LOCK:
        print(*args, **kwargs)


# ============================================================
# EMAIL SENDER
# ============================================================
def send_email(html_body: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Daily Expires Report <{SMTP_SENDER}>"
    msg["To"] = SMTP_RECEIVER
    msg['Cc'] = SMTP_CC
    msg["Subject"] = "🚨 Action Required: Expiring Jobs Alert"

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SMTP_SENDER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        safe_print("📧 Alert Email Sent Successfully!")
    except Exception as e:
        safe_print("❌ Email sending failed:", e)


# ============================================================
# DB ROUTING
# ============================================================
def pick_db(dtype, domain):
    dtype = (dtype or "").lower()
    clean = domain.split("/")[0].split(".")[0].lower()

    if dtype == "proxy":
        return "prod_jobiak_ai", "job"
    if "sub" in dtype:
        return "directclients_prod", "Target_P4_Opt"

    return f"{clean}_prod", "Target_P4_Opt"


# ============================================================
# FASTER REMOTE CONNECTION
# ============================================================
def get_remote(dbname, local):
    if not dbname: return None, 0.0
    t0 = time.time()

    rec = local["mongo_creds"]["creds"].find_one({"domain": dbname})
    if not rec or "mongo_uri" not in rec: return None, round(time.time() - t0, 3)

    uri = rec["mongo_uri"]

    with CACHE_LOCK:
        if uri in CLIENT_CACHE:
            return CLIENT_CACHE[uri], round(time.time() - t0, 3)

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        with CACHE_LOCK:
            CLIENT_CACHE[uri] = client
        return client, round(time.time() - t0, 3)
    except Exception as e:
        safe_print(f"❌ Connection failed for {dbname}: {e}")
        return None, round(time.time() - t0, 3)


# ============================================================
# PROCESS DOMAIN
# ============================================================
def process_domain(dom, utc, local):
    dom_start = time.time()
    domain = dom.get("Domain", "Unknown")
    dtype = (dom.get("Domain Type") or "")
    quota = dom.get("Quota", 0)
    emp = dom.get("EmployerId")

    safe_print(f"➡️ Checking: {domain} [{dtype}]")

    day_start = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_dt = day_start + timedelta(days=5)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%dT00:00:00.000+0000")

    # Build DB Queries & Strings
    if dtype.lower() == "proxy":
        pymongo_query = {
            "status": "posted",
            "isActive": True,
            "datePosted": {"$exists": True},
            "validThrough": {"$lt": cutoff_dt}
        }
        if emp: pymongo_query["employerId"] = emp

        emp_part = f'"employerId" : "{emp}", ' if emp else ""
        display_query = f'{{ {emp_part}"status" : "posted", "isActive" : true, "datePosted" : {{ $exists : true }}, "validThrough" : {{ $lt : ISODate("{cutoff_str}") }} }}'
    else:
        pymongo_query = {
            "pub_expired": {"$lt": cutoff_dt},
            "gpost": 5,
            "job_status": {"$ne": 3}
        }
        if emp: pymongo_query["employerId"] = emp

        emp_part = f', "employerId": "{emp}"' if emp else ""
        display_query = f'{{ "pub_expired": {{ $lt: ISODate("{cutoff_str}") }}, "gpost": NumberInt(5), "job_status": {{ $ne: NumberInt(3) }}{emp_part} }}'

    dbname, colname = pick_db(dtype, domain)
    client, conn_lat = get_remote(dbname, local)

    if not client:
        return finalize(domain, dtype, quota, cutoff_str, f"ERROR: Connection Failed for {dbname}", conn_lat, 0,
                        dom_start, 0)

    col = client[dbname][colname]

    # Execute Count with Index Hint to prevent 600s+ full scans
    t = time.time()
    try:
        # First attempt with Hint for blazing fast returns on large Programmatic collections
        kwargs = {}
        if dtype.lower() != "proxy":
            kwargs["hint"] = "pub_expired_1_gpost_1"
        job_count = col.count_documents(pymongo_query, **kwargs)
    except Exception as e:
        # Fallback if index is missing
        try:
            job_count = col.count_documents(pymongo_query)
        except Exception as e2:
            safe_print(f"❌ Query Error: {e2}")
            job_count = 0
            display_query = f"ERROR Execution Failed: {e2}"

    query_lat = time.time() - t
    safe_print(f"   ✔️ {domain} | Jobs: {job_count} | Time: {round(time.time() - dom_start, 2)}s")

    return finalize(domain, dtype, quota, cutoff_str, display_query, conn_lat, query_lat, dom_start, job_count)


def finalize(domain, dtype, quota, cutoff_date, query, conn_lat, query_lat, dom_start, job_count):
    return {
        "Domain": domain, "Type": dtype, "Quota": quota, "CutoffDate": cutoff_date,
        "JobCount": job_count, "Query": query, "Conn": round(conn_lat, 3),
        "QueryLat": round(query_lat, 3), "Total": round(time.time() - dom_start, 3)
    }


def process_domain_safe(dom, utc, local):
    try:
        return process_domain(dom, utc, local)
    except Exception as e:
        return finalize(dom.get("Domain"), dom.get("Domain Type"), dom.get("Quota"), "-", f"ERROR: {e}", 0, 0,
                        time.time(), 0)


# ============================================================
# MAIN
# ============================================================
def main():
    script_start = time.time()
    safe_print("🔥 EXPIRING JOBS SCRIPT STARTED")

    local = MongoClient(LOCAL_MONGO_URI)
    domains = list(local["domain_postings"]["domains"].find({}, {"_id": 0}))

    utc = datetime.now(timezone.utc)
    results = []

    with ThreadPoolExecutor(max_workers=25) as pool:
        futures = [pool.submit(process_domain_safe, d, utc, local) for d in domains]
        for f in as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda x: x["JobCount"] if isinstance(x["JobCount"], int) else 0, reverse=True)

    domain_cards_html = ""
    action_required_count = 0

    for r in results:
        has_jobs = isinstance(r['JobCount'], int) and r['JobCount'] > 0

        if has_jobs:
            action_required_count += 1
            indicator_color = "#FF3B30"  # Apple Red
            info_block = f"""
            <div style="margin-top:16px; padding-top:16px; border-top:1px solid rgba(0,0,0,0.04);">
                <span style="color:#86868B; font-size:12px; display:block; margin-bottom:4px; text-transform:uppercase; letter-spacing:0.02em; font-weight:600;">Expiring Before</span>
                <b style="font-size:15px; color:#1D1D1F;">{r['CutoffDate'][:10]}</b>
            </div>
            <div style="margin-top:16px; padding:16px; background:rgba(245, 245, 247, 0.8); border-radius:12px; border:1px solid rgba(0,0,0,0.04); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size:12px; color:#1D1D1F; overflow-x:auto;">
                {r['Query']}
            </div>
            """
        else:
            indicator_color = "#34C759"  # Apple Green
            info_block = ""

        # Using a solid table layout for the header ensures true "auto layout" grid rendering inside of emails
        domain_cards_html += f"""
        <div style="background:#FFFFFF; border-radius:20px; padding:24px; margin-bottom:20px; box-shadow:0 4px 24px rgba(0, 0, 0, 0.04); border:1px solid rgba(0,0,0,0.02);">

            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                    <td align="left" valign="middle">
                        <h3 style="margin:0 0 6px 0; font-size:18px; font-weight:600; color:#1D1D1F; letter-spacing:-0.02em;">{r['Domain']}</h3>
                        <span style="display:inline-block; padding:4px 10px; background:#F5F5F7; border-radius:8px; font-size:12px; color:#86868B; font-weight:500;">{r['Type']}</span>
                    </td>
                    <td align="right" valign="middle">
                        <div style="font-size:26px; font-weight:700; color:{indicator_color}; letter-spacing:-0.04em; line-height:1;">{r['JobCount']}</div>
                        <div style="font-size:12px; color:#86868B; font-weight:500; margin-top:6px;">Jobs Expiring</div>
                    </td>
                </tr>
            </table>

            {info_block}

            <div style="margin-top:20px; font-size:11px; color:#A1A1A6; text-transform:uppercase; letter-spacing:0.04em; font-weight:500;">
                DB: {r['Conn']}s &nbsp;&middot;&nbsp; Query: {r['QueryLat']}s &nbsp;&middot;&nbsp; Total: {r['Total']}s
            </div>
        </div>
        """

    total_runtime = round(time.time() - script_start, 2)

    # Apple-style Glassmorphism & Bento Grid Base
    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#F5F5F7; font-family:-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing:antialiased;"> 

<div style="max-width:680px; margin:0 auto; padding:40px 20px;">

    <div style="text-align:center; margin-bottom:32px;">
        <div style="display:inline-block; background:rgba(255, 59, 48, 0.1); color:#FF3B30; padding:6px 16px; border-radius:20px; font-weight:600; font-size:13px; margin-bottom:16px; letter-spacing:-0.01em;">
            Action Required
        </div>
        <h1 style="margin:0 0 12px 0; font-size:32px; font-weight:700; color:#1D1D1F; letter-spacing:-0.04em;">Expiring Jobs Alert</h1>
        <p style="margin:0; font-size:16px; line-height:1.5; color:#515154;">The following domains have jobs dropping off in the next <strong>5 days</strong>. Please update them to maintain target quotas.</p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
        <tr>
            <td width="31%" valign="top">
                <div style="background:#FFFFFF; padding:20px; border-radius:20px; box-shadow:0 4px 20px rgba(0,0,0,0.03); text-align:center;">
                    <div style="font-size:28px; font-weight:700; color:#1D1D1F; letter-spacing:-0.04em;">{total_runtime}s</div>
                    <div style="font-size:13px; color:#86868B; font-weight:500; margin-top:4px;">Scan Runtime</div>
                </div>
            </td>
            <td width="3.5%"></td>
            <td width="31%" valign="top">
                <div style="background:#FFFFFF; padding:20px; border-radius:20px; box-shadow:0 4px 20px rgba(0,0,0,0.03); text-align:center;">
                    <div style="font-size:28px; font-weight:700; color:#1D1D1F; letter-spacing:-0.04em;">{len(domains)}</div>
                    <div style="font-size:13px; color:#86868B; font-weight:500; margin-top:4px;">Domains Checked</div>
                </div>
            </td>
            <td width="3.5%"></td>
            <td width="31%" valign="top">
                <div style="background:rgba(255, 59, 48, 0.05); border:1px solid rgba(255, 59, 48, 0.1); padding:20px; border-radius:20px; text-align:center;">
                    <div style="font-size:28px; font-weight:700; color:#FF3B30; letter-spacing:-0.04em;">{action_required_count}</div>
                    <div style="font-size:13px; color:#FF3B30; font-weight:600; margin-top:4px;">Need Updates</div>
                </div>
            </td>
        </tr>
    </table>

    {domain_cards_html}

    <div style="margin-top:48px; text-align:center;">
        <p style="margin:0; font-size:12px; color:#86868B; font-weight:500;">Automated Expiration Monitor</p>
        <p style="margin:6px 0 0 0; font-size:12px; color:#A1A1A6;">This is a System Generated Mail</p>
    </div>

</div>

</body>
</html>
"""
    send_email(html)


if __name__ == "__main__":
    main()