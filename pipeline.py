# pipeline.py
import re
import gzip
import io
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SPREADSHEET_ID = "1QDcjhsg9PdjpZd1o10KdijKIYDLu-2cQLCIkMgDgHow"

# =====================================================
# FILE INGESTION (FROM FASTAPI UPLOAD)
# =====================================================

def import_uploaded_report(uploaded_file, report_type: str, date: str) -> pd.DataFrame:
    raw = uploaded_file.file.read()

    if uploaded_file.filename.endswith(".gz"):
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)

    if df.empty:
        return df

    df["report_type"] = report_type
    df["date"] = date

    # Clean revenue columns
    for c in df.columns:
        if re.search(r"(revenue|payout|price)", c, re.I):
            df[c] = (
                df[c]
                .replace(r"[^0-9.\-]", "", regex=True)
                .astype(float, errors="ignore")
                .fillna(0)
            )

    if "action_type" in df.columns:
        df["action_type"] = df["action_type"].astype(str).str.lower()

    job_col = next((c for c in df.columns if "job" in c.lower() and "id" in c.lower()), None)
    df["job_id_clean"] = df[job_col].apply(clean_job_id) if job_col else None

    return df


# =====================================================
# HELPERS
# =====================================================

def clean_job_id(v):
    if not v:
        return None
    s = str(v).strip()
    s = s[1:] if s.startswith("'") else s
    s = re.sub(r"[^0-9]", "", s)
    return s or None

def normalize_minute(ts):
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)[:16].replace("T", " ")

def to_db_key(domain):
    v = str(domain).strip()
    if v.endswith("_prod"):
        return v
    if "." in v:
        return f"{v.split('.')[0]}_prod"
    return f"{v}_prod"

def safe_lower_series(s):
    return s.astype(str).str.strip().str.lower()

def get_or_create_worksheet(sheet, name, rows=300, cols=50):
    for ws in sheet.worksheets():
        if ws.title.lower().strip() == name.lower().strip():
            return ws
    return sheet.add_worksheet(title=name, rows=rows, cols=cols)


# =====================================================
# LOAD CONFIG FROM SHEET / MONGO
# =====================================================

def load_domains(sheet):
    ws = get_or_create_worksheet(sheet, "Domains")
    rows = ws.get_all_records()
    return [str(r.get("domain", "")).strip() for r in rows if r.get("domain")]

def load_mongo_creds(mongo_client, domains):
    col = mongo_client["mongo_creds"]["creds"]
    res = list(col.find({"domain": {"$in": domains}}, {"_id": 0}))
    return {r["domain"]: {"uri": r["mongo_uri"], "db": r["domain"]} for r in res}


# =====================================================
# FETCH VIEWS (FIXED)
# =====================================================

def extract_api_job_id(*urls):
    for u in urls:
        if not u:
            continue
        m = re.search(r"(job[_-]?id=|/job/|/viewjob/.*?)([0-9]{6,})", str(u), re.I)
        if m:
            return clean_job_id(m.group(2))
    return None

def fetch_views(uri, db_name, date):
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[db_name]

        start = datetime.strptime(date, "%Y-%m-%d")
        end = start + timedelta(days=1, hours=6)

        col = db["userAnalytics"]

        q = {
            "isBot": False,
            "isFromGoogle": True,
            "createdDt": {"$gte": start, "$lt": end},
            "$or": [
                {"extraInfo.sourceEmployerId": "emp-gxc-jobgetcpa1"},
                {"extraInfo.sourceEmployerId": "emp-gxc-jobgetcpc1"},
                {"extraInfo.url": {"$regex": "^https://job-api.jobget.com", "$options": "i"}},
            ]
        }

        docs = list(col.find(q, {
            "_id": 0,
            "company": 1,
            "createdDt": 1,
            "submittedUrl": 1,
            "extraInfo": 1
        }))

        for d in docs:
            ei = d.get("extraInfo") or {}
            d["domain"] = db_name
            d["apiJobId"] = extract_api_job_id(ei.get("url"), d.get("submittedUrl"))
            d["trimmed_createdDt"] = normalize_minute(d.get("createdDt"))

        logging.info(f"{db_name}: {len(docs)} views")
        return docs

    except Exception as e:
        logging.error(f"{db_name}: {e}")
        return []


# =====================================================
# STATS LOGIC (SAFE)
# =====================================================

def normalize_paid(v):
    return str(v).strip().lower() in {
        "1", "true", "paid", "yes", "jobget", "jobgetcpa1", "jobget_cpa"
    }

def split_paid_unpaid(df):
    if df.empty:
        return df.copy(), df.copy()

    mask = df.apply(
        lambda r: any(normalize_paid(r.get(c, "")) for c in df.columns if "paid" in c.lower()),
        axis=1
    )
    return df[mask].copy(), df[~mask].copy()

def revenue_columns(df):
    return [c for c in df.columns if re.search(r"(revenue|payout|price)", c, re.I)]

def build_stats(report_df, paid_df, unpaid_df):
    if report_df.empty:
        return pd.DataFrame()

    rev_cols = revenue_columns(report_df)

    rows = []
    for domain in sorted(report_df["matched_domain"].dropna().unique()):
        p = paid_df[paid_df["matched_domain"] == domain]
        u = unpaid_df[unpaid_df["matched_domain"] == domain]

        rows.append({
            "Domain": domain,
            "Paid Clicks": int((safe_lower_series(p.get("action_type", "")) == "click").sum()),
            "Unpaid Clicks": int((safe_lower_series(u.get("action_type", "")) == "click").sum()),
            "Paid Applies": int((safe_lower_series(p.get("action_type", "")) == "apply").sum()),
            "Unpaid Applies": int((safe_lower_series(u.get("action_type", "")) == "apply").sum()),
            "Paid Revenue ($)": float(p[rev_cols].sum().sum()) if rev_cols else 0,
            "Unpaid Revenue ($)": float(u[rev_cols].sum().sum()) if rev_cols else 0,
        })

    return pd.DataFrame(rows)

def add_derived(df, date):
    df = df.copy()
    df["Total Clicks"] = df["Paid Clicks"] + df["Unpaid Clicks"]
    df["Revenue per Click ($)"] = (
        (df["Paid Revenue ($)"] + df["Unpaid Revenue ($)"])
        / df["Total Clicks"].replace(0, pd.NA)
    ).fillna(0)
    df["Last Updated (IST)"] = datetime.now(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%Y-%m-%d %H:%M:%S")
    df["date"] = date
    return df


# =====================================================
# PIPELINE ENTRY (CALLED BY FASTAPI)
# =====================================================

def run_pipeline(report_df, date, gspread_client, mongo_uri):
    sheet = gspread_client.open_by_key(SPREADSHEET_ID)
    mongo = MongoClient(mongo_uri)

    domains = load_domains(sheet)
    db_keys = [to_db_key(d) for d in domains]
    creds = load_mongo_creds(mongo, db_keys)

    # FETCH VIEWS
    all_views = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [
            ex.submit(fetch_views, creds[d]["uri"], creds[d]["db"], date)
            for d in creds
        ]
        for f in as_completed(futures):
            all_views.extend(f.result())

    views = pd.DataFrame(all_views)

    def write(name, df):
        ws = get_or_create_worksheet(sheet, name)
        ws.clear()
        if df.empty:
            ws.update([["(no rows)"]])
        else:
            ws.update([df.columns.tolist()] + df.fillna("").astype(str).values.tolist())

    write("Views", views)

    views["apiJobId"] = views["apiJobId"].apply(clean_job_id)
    domain_map = dict(zip(views["apiJobId"], views["domain"]))
    company_map = dict(zip(views["apiJobId"], views["company"]))

    report_df["job_id_clean"] = report_df["job_id_clean"].apply(clean_job_id)
    report_df["matched_domain"] = report_df["job_id_clean"].map(domain_map).fillna("UNMATCHED")
    report_df["company"] = report_df["job_id_clean"].map(company_map).fillna("")

    cpa = report_df[report_df["report_type"] == "CPA"].copy()
    cpc = report_df[report_df["report_type"] == "CPC"].copy()

    write("cpa_report", cpa)
    write("cpc_report", cpc)

    paid_all, unpaid_all = split_paid_unpaid(report_df)
    write("Stats", add_derived(build_stats(report_df, paid_all, unpaid_all), date))

    cpa_paid, cpa_unpaid = split_paid_unpaid(cpa)
    write("cpa_stats", add_derived(build_stats(cpa, cpa_paid, cpa_unpaid), date))

    cpc_paid, cpc_unpaid = split_paid_unpaid(cpc)
    write("cpc_stats", add_derived(build_stats(cpc, cpc_paid, cpc_unpaid), date))

    return {
        "domains": len(creds),
        "views": len(views),
    }
