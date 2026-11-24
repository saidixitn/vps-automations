import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
import smtplib
from pymongo import MongoClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv
load_dotenv()
# ==========================================================
# CONFIG
# ==========================================================
LOCAL_MONGO_URI = os.getenv("MONGO_URI")           
if not LOCAL_MONGO_URI:
    raise Exception("LOCAL_MONGO_URI not found in environment variables") 
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = "saidixitn@gmail.com"
SMTP_PASS = os.getenv("SMTP_PASS")       # Gmail App Password
if not SMTP_PASS:
    raise Exception("SMTP_PASS not found in environment variables") 
CREDENTIALS_FILE = "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ==========================================================
# DATE ARG
# ==========================================================
if len(sys.argv) < 2:
    print("Usage: python stats_email.py YYYY-MM-DD")
    sys.exit(1)

REPORT_DATE = sys.argv[1]
MIN_DT = datetime.strptime(REPORT_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
MAX_DT = MIN_DT + timedelta(days=1)

# ==========================================================
# HELPERS
# ==========================================================
def clean_domain(d: str) -> str:
    return (d or "").replace("https://", "").replace("http://", "").strip()

def to_int(v) -> int:
    try:
        return int(v)
    except:
        return 0

def normalize_type(t) -> str:
    return str(t or "").strip().lower()

def is_table_domain(domain_type: str) -> bool:
    return normalize_type(domain_type) in {
        "programmatic",
        "direct apply",
        "direct_apply",
        "direct-apply",
    }

# ==========================================================
# GOOGLE SHEETS
# ==========================================================
creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open("Domain Stats")
domains_ws = sheet.worksheet("Domains")
domains_rows = domains_ws.get_all_records()

# Normalize/trim sheet rows early (avoid NaN-like weirdness)
for r in domains_rows:
    r["Domain"] = (r.get("Domain") or "").strip()
    r["Database"] = (r.get("Database") or "").strip()
    r["Domain Type"] = (r.get("Domain Type") or "").strip()
    r["EmployerId"] = (str(r.get("EmployerId") or "")).strip()
    # Optional columns may exist
    r["Collection"] = (r.get("Collection") or "").strip()

# ==========================================================
# MONGO
# ==========================================================
client = MongoClient(LOCAL_MONGO_URI)
domains_col = client["mongo_creds"]["creds"]
stats_col = client["daily_domain_stats"]["stats"]
email_col = client["daily_domain_stats"]["email"]

# ==========================================================
# MONGO CONNECT
# ==========================================================
def connect_mongo(domain_record, db_name):
    c = MongoClient(domain_record["mongo_uri"], serverSelectionTimeoutMS=8000)
    c.admin.command("ping")
    return c[db_name]

# ==========================================================
# FETCH VIEWS (FIXED)
# - If EmployerId is empty -> do NOT filter by employerId
# - Calculates End Url Domain from url/submittedUrl
# - Uses sourceEmployerId, falling back to End Url Domain if null
# ==========================================================
def fetch_views(domain, db, employer_id, domain_type):
    col = db["userAnalytics"]

    match = {
        "isBot": False,
        "browserType": {"$ne": "Unknown"},
        "deviceType": {"$ne": "Unknown"},
        "isFromGoogle": True,
        "createdDt": {"$gt": MIN_DT, "$lt": MAX_DT},
    }

    if employer_id:
        match["employerId"] = employer_id

    pipeline = [
        {"$match": match},
        {"$project": {
            "Company": {"$ifNull": ["$company", {"$ifNull": ["$companyName", "Unknown"]}]},
            "date": {"$substr": ["$createdDt", 0, 10]},
            "url": 1,
            "submittedUrl": 1,
            "ipAddress": 1,
            "extraInfo": 1,
        }},
        {"$addFields": {
            "targetUrl": {"$ifNull": ["$url", {"$ifNull": ["$submittedUrl", ""]}]}
        }},
        {"$addFields": {
            "calculatedEndUrl": {
                "$ifNull": [
                    {
                        "$arrayElemAt": [
                            {"$split": ["$targetUrl", "/"]},
                            2
                        ]
                    },
                    ""
                ]
            }
        }},
        {"$addFields": {
            "sourceEmployerId": {
                "$ifNull": ["$extraInfo.sourceEmployerId", "$calculatedEndUrl"]
            }
        }},
        {"$group": {
            "_id": {
                "Company": "$Company",
                "SourceEmployerId": "$sourceEmployerId",
                "Date": "$date",
            },
            "ViewsCount": {"$sum": 1},
            "UniqueIpCount": {"$addToSet": "$ipAddress"},
        }},
        {"$project": {
            "_id": 0,
            "Date": "$_id.Date",
            "Company": "$_id.Company",
            "sourceEmployerId": {"$ifNull": ["$_id.SourceEmployerId", ""]},
            "ViewsCount": 1,
            "UniqueIpCount": {"$size": "$UniqueIpCount"},
            "Domain": domain,
            "Domain Type": domain_type,
        }},
    ]

    return list(col.aggregate(pipeline, allowDiskUse=True))

# ==========================================================
# DOMAIN WORKER
# ==========================================================
def process_domain(row):
    domain = row["Domain"]
    db_name = row["Database"]
    domain_type = row["Domain Type"]
    employer_id = row["EmployerId"]

    if not domain or not db_name:
        return []

    record = domains_col.find_one({"domain": db_name})
    if not record:
        return []

    db = connect_mongo(record, db_name)
    return fetch_views(domain, db, employer_id, domain_type)

# ==========================================================
# RUN STATS
# ==========================================================
# Optional: clean old stats for that date
stats_col.delete_many({"Date": REPORT_DATE})

all_rows = []
with ThreadPoolExecutor(max_workers=8) as ex:
    futures = [ex.submit(process_domain, r) for r in domains_rows]
    for f in as_completed(futures):
        all_rows.extend(f.result())

for r in all_rows:
    r["InsertedAt"] = datetime.now(timezone.utc)

if all_rows:
    stats_col.insert_many(all_rows)

# ==========================================================
# AGGREGATE FOR EMAIL (DOMAIN-DRIVEN)
# - Initialize every domain from sheet with 0s so it always appears
# ==========================================================
domains = defaultdict(lambda: {
    "type": "",
    "clicks": 0,
    "ips": 0,
    "rows": defaultdict(lambda: {"clicks": 0, "ips": 0})
})

# Seed domains from Google Sheet so zero-traffic domains still show up
for r in domains_rows:
    dom = r["Domain"]
    if not dom:
        continue
    domains[dom]["type"] = r["Domain Type"]

# Aggregate actual rows
for r in all_rows:
    dom = r.get("Domain", "")
    if not dom:
        continue

    d = domains[dom]
    d["type"] = r.get("Domain Type", d["type"])

    clicks = to_int(r.get("ViewsCount", 0))
    ips = to_int(r.get("UniqueIpCount", 0))

    d["clicks"] += clicks
    d["ips"] += ips

    company = r.get("Company", "Unknown")
    source_employer_id = r.get("sourceEmployerId", "") or ""
    key = (company, source_employer_id)

    d["rows"][key]["clicks"] += clicks
    d["rows"][key]["ips"] += ips

# ==========================================================
# HTML BUILDER (PIXEL MATCH + CORRECT TYPE DISPLAY)
# ==========================================================
def build_html(name, email):
    total_domains = len(domains)
    total_clicks = sum(d["clicks"] for d in domains.values())
    total_ips = sum(d["ips"] for d in domains.values())

    # Count unique companies observed in the data (not from proxy domains)
    companies = {c for d in domains.values() for (c, _) in d["rows"].keys()}

    blocks = ""

    for domain, d in sorted(domains.items(), key=lambda x: x[1]["clicks"], reverse=True):
        domain_type = d.get("type", "") or ""
        table = ""

        if is_table_domain(domain_type):
            rows_html = ""
            # Sort rows by clicks descending for nicer email
            row_items = sorted(d["rows"].items(), key=lambda kv: kv[1]["clicks"], reverse=True)
            for (company, source_emp_id), s in row_items:
                if not source_emp_id:
                    continue
                rows_html += f"""
  <tr>
  <td style="padding: 10px;">{company}</td>
  <td style="padding: 10px;">{source_emp_id}</td>
  <td style="padding: 10px; text-align: right;">{s['clicks']}</td>
  <td style="padding: 10px; text-align: right;">{s['ips']}</td>
  </tr>
"""

            table = f"""
  <table style="width: 100%; border-collapse: collapse; margin-top: 18px; background: #fafbff; border-radius: 14px; overflow: hidden; border: 1px solid #e2e7ff;">
  <thead>
  <tr style="background: #eef2ff;">
  <th style="padding: 10px; font-size: 12px; text-align: left;">Company</th>
  <th style="padding: 10px; font-size: 12px; text-align: left;">sourceEmployerId</th>
  <th style="padding: 10px; font-size: 12px; text-align: right;">Clicks</th>
  <th style="padding: 10px; font-size: 12px; text-align: right;">Unique IPs</th>
  </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
  </table>
"""

            # Use the actual domain type label (Programmatic OR Direct Apply)
            blocks += f"""
  <div style="padding: 26px; margin-bottom: 28px; border-radius: 24px; background: #ffffff; border: 1px solid #e4e6ef; box-shadow: 0 8px 24px rgba(99,102,241,0.14);">
  <h3 style="margin: 0 0 6px 0; font-size: 20px; color: #4f46e5; font-weight: 600;">{clean_domain(domain)}</h3>
  <div style="font-size: 14px; color: #374151; margin-bottom: 14px;"><strong>Domain Type:</strong>
  <span style="display: inline-block; padding: 3px 10px; border-radius: 999px; background: #eef2ff; color: #4338ca; font-size: 12px; font-weight: 600;"> {domain_type} </span></div>
  <div style="margin-top: 10px; font-size: 15px;"><strong>Total Clicks:</strong> {d['clicks']} &nbsp;&nbsp; <strong>Unique IPs:</strong> {d['ips']}</div>
{table}
  </div>
"""
        else:
            blocks += f"""
  <div style="padding: 26px; margin-bottom: 28px; border-radius: 24px; background: #ffffff; border: 1px solid #e4e6ef; box-shadow: 0 8px 24px rgba(99,102,241,0.14);">
  <h3 style="margin: 0 0 6px 0; font-size: 20px; color: #4f46e5; font-weight: 600;">{clean_domain(domain)}</h3>
  <div style="font-size: 14px; color: #374151; margin-bottom: 12px;"><strong>Domain Type:</strong> {domain_type}</div>
  <div style="font-size: 15px; line-height: 1.6;"><strong>Clicks:</strong> {d['clicks']}<br /> <strong>Unique IPs:</strong> {d['ips']}</div>
  </div>
"""

    return f"""
  <p>&nbsp;</p>
  <div style="padding: 40px;">
  <div style="max-width: 840px; margin: 0 auto; background: linear-gradient(145deg,#ffffff,#f5f7ff); padding: 44px; border-radius: 28px; box-shadow: 0 14px 36px rgba(80,80,200,0.18); font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <h1 style="margin: 0 0 8px 0; font-size: 28px; font-weight: 500; color: #111827; letter-spacing: -0.4px; line-height: 1.2;">Hey {name},</h1>
  <h3 style="margin: 0 0 26px 0; font-size: 17px; font-weight: 600; color: #6b7280; line-height: 1.5;">Here&rsquo;s your daily domain wise clicks report.</h3>
  <h1 style="margin: 0 0 10px 0; font-size: 30px; font-weight: 600; color: #4338ca; letter-spacing: -0.4px;">Daily Domain Wise Clicks Report ⚡</h1>
  <p style="margin: 0 0 30px 0; color: #6b7280; font-size: 15px;">Date: <strong>{REPORT_DATE}</strong></p>
  <div style="background: linear-gradient(135deg,#e4e7ff,#d8dcff); padding: 22px 26px; border-radius: 22px; border-left: 6px solid #6366f1; margin-bottom: 36px;">
  <div style="font-size: 15px; color: #374151; line-height: 1.7;"><strong>🌐 Domains:</strong> {total_domains}<br /> <strong>🏢 Companies:</strong> {len(companies)}<br /> <strong>🖱 Total Clicks:</strong> {total_clicks:,}<br /> <strong>🧍 Unique IPs:</strong> {total_ips:,}</div>
  </div>

{blocks}

  <div style="margin-top: 42px; text-align: center; color: #9ca3af; font-size: 13px;">Sent to <strong>{name}</strong> &middot; {email}<br /> Generated automatically &middot; Daily Domain Analytics</div>
  </div>
  </div>
"""

# ==========================================================
# SEND EMAIL
# ==========================================================
server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
server.login(SMTP_USER, SMTP_PASS)

for r in email_col.find({}, {"_id": 0}):
    msg = MIMEMultipart("alternative")
    msg["From"] = "Daily Clicks Report"
    msg["To"] = r["email"]
    msg["Subject"] = f"Daily Domain Click Report - {REPORT_DATE}"
    msg.attach(MIMEText(build_html(r.get("Name", "There"), r.get("email", "")), "html"))
    server.send_message(msg)

server.quit()
print("🚀 Email sent successfully.")