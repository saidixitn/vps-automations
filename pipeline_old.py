import re
import logging
import gzip
import io
import pandas as pd
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SPREADSHEET_ID = "1QDcjhsg9PdjpZd1o10KdijKIYDLu-2cQLCIkMgDgHow"

# =========================================================
# FILE INGESTION (FASTAPI UPLOAD)
# =========================================================

def import_uploaded_report(uploaded_file, report_type: str, date_str: str) -> pd.DataFrame:
    """
    Reads CSV / CSV.GZ uploaded via FastAPI and normalizes it
    """

    raw = uploaded_file.file.read()

    if uploaded_file.filename.endswith(".gz"):
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)

    if df.empty:
        return df

    df["report_type"] = report_type
    df["date"] = date_str

    # Clean revenue columns
    for c in df.columns:
        if any(k in c.lower() for k in ("revenue", "payout", "price")):
            df[c] = (
                df[c]
                .replace(r"[^0-9.\-]", "", regex=True)
                .astype(float, errors="ignore")
                .fillna(0)
            )

    # Normalize action_type
    if "action_type" in df.columns:
        df["action_type"] = df["action_type"].astype(str).str.lower()

    # Extract job ID
    job_col = next(
        (c for c in df.columns if "job" in c.lower() and "id" in c.lower()),
        None
    )
    df["job_id_clean"] = df[job_col].apply(clean_job_id) if job_col else None

    return df


# =========================================================
# HELPERS
# =========================================================

def get_or_create_worksheet(sheet, name, rows=300, cols=50):
    for ws in sheet.worksheets():
        if ws.title.lower().strip() == name.lower().strip():
            return ws
    return sheet.add_worksheet(title=name, rows=rows, cols=cols)

def clean_job_id(value):
    if value is None:
        return None
    s = str(value).strip()
    if s.startswith("'"):
        s = s[1:]
    s = re.sub(r"[^0-9]", "", s)
    return s if s else None

def normalize_minute(ts):
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    try:
        return str(ts)[:16].replace("T", " ")
    except Exception:
        return None

def to_db_key(domain):
    v = str(domain).strip()
    if v.endswith("_prod"):
        return v
    if "." in v:
        return f"{v.split('.')[0]}_prod"
    return f"{v}_prod"

def safe_lower_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()


# =========================================================
# GOOGLE SHEET LOADERS
# =========================================================

def load_domains(sheet):
    ws = get_or_create_worksheet(sheet, "Domains")
    data = ws.get_all_records()
    return [str(d.get("domain", "")).strip() for d in data if d.get("domain")]


# =========================================================
# MONGO LOADERS
# =========================================================

def load_mongo_creds(mongo_client, domains):
    creds_col = mongo_client["mongo_creds"]["creds"]
    res = list(creds_col.find({"domain": {"$in": domains}}, {"_id": 0}))
    return {r["domain"]: {"uri": r["mongo_uri"], "db": r["domain"]} for r in res}


# =========================================================
# VIEWS FETCH
# =========================================================

def flatten_extra(doc):
    ei = doc.get("extraInfo") or {}
    doc["extraInfo.url"] = ei.get("url")
    doc["extraInfo.sourceEmployerId"] = ei.get("sourceEmployerId")
    return doc

def extract_api_job_id(*urls):
    for u in urls:
        if not u:
            continue
        u = str(u)

        m = re.search(r"/job/([\w\-]+)", u, re.I)
        if m:
            return clean_job_id(m.group(1))

        m = re.search(r"job[_-]?id=([\w\-]+)", u, re.I)
        if m:
            return clean_job_id(m.group(1))

        m = re.search(r"/viewjob/.*?([0-9]{6,})", u, re.I)
        if m:
            return clean_job_id(m.group(1))

    return None

def fetch_views(uri, db_name, date_str):
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=4500)
        db = client[db_name]

        start = datetime.strptime(date_str, "%Y-%m-%d")
        end = start + timedelta(days=1, hours=6)

        projection = {
            "_id": 0,
            "ipAddress": 1,
            "company": 1,
            "createdDt": 1,
            "submittedUrl": 1,
            "extraInfo": 1
        }

        q1_cpa = {
            "isBot": False,
            "isFromGoogle": True,
            "createdDt": {"$gte": start, "$lt": end},
            "extraInfo.sourceEmployerId": "emp-gxc-jobgetcpa1"
        }

        q1_cpc = {
            "isBot": False,
            "isFromGoogle": True,
            "createdDt": {"$gte": start, "$lt": end},
            "extraInfo.sourceEmployerId": "emp-gxc-jobgetcpc1"
        }

        q2 = {
            "isBot": False,
            "isFromGoogle": True,
            "createdDt": {"$gte": start, "$lt": end},
            "extraInfo.url": {"$regex": "^https://job-api.jobget.com.*", "$options": "i"}
        }

        col = db["userAnalytics"]

        docs = list(col.find(q1_cpa, projection))
        docs += list(col.find(q1_cpc, projection))

        if not docs:
            docs = list(col.find(q2, projection))

        for d in docs:
            flatten_extra(d)
            d["domain"] = db_name
            d["apiJobId"] = clean_job_id(
                extract_api_job_id(d.get("extraInfo.url"), d.get("submittedUrl"))
            )
            d["trimmed_createdDt"] = normalize_minute(d.get("createdDt"))

        logging.info(f"{db_name}: {len(docs)} views")
        return db_name, True, docs

    except Exception as e:
        logging.error(f"{db_name}: {e}")
        return db_name, False, []


# =========================================================
# STATS
# =========================================================

def normalize_paid(v):
    return str(v).strip().lower() in [
        "1", "true", "paid", "yes", "y", "jobget", "jobgetcpa1", "jobget_cpa"
    ]

def split_paid_unpaid(df):
    if df.empty:
        return df.copy(), df.copy()

    paid_mask = df.apply(
        lambda r: any(
            normalize_paid(r.get(c, "")) for c in df.columns if "paid" in c.lower()
        ),
        axis=1
    )
    return df[paid_mask].copy(), df[~paid_mask].copy()

def revenue_columns(df):
    return [c for c in df.columns if re.search(r"(revenue|payout|price)", c, re.I)]

def build_stats_for_report(report_df, paid_df, unpaid_df):
    if report_df.empty:
        return pd.DataFrame()

    rev_cols = revenue_columns(report_df)

    def clicks(df):
        return int((safe_lower_series(df.get("action_type", "")) == "click").sum())

    def applies(df):
        return int((safe_lower_series(df.get("action_type", "")) == "apply").sum())

    rows = []
    for domain in sorted(report_df["matched_domain"].dropna().unique()):
        p = paid_df[paid_df["matched_domain"] == domain]
        u = unpaid_df[unpaid_df["matched_domain"] == domain]

        rows.append({
            "Domain": domain,
            "Paid Clicks": clicks(p),
            "Unpaid Clicks": clicks(u),
            "Paid Applies": applies(p),
            "Unpaid Applies": applies(u),
            "Paid Revenue ($)": float(p[rev_cols].sum().sum()) if rev_cols else 0,
            "Unpaid Revenue ($)": float(u[rev_cols].sum().sum()) if rev_cols else 0,
        })

    return pd.DataFrame(rows)

def add_derived_columns(df, date):
    df = df.copy()
    df["Total Clicks"] = df["Paid Clicks"] + df["Unpaid Clicks"]
    df["Revenue per Click ($)"] = (
        (df["Paid Revenue ($)"] + df["Unpaid Revenue ($)"])
        / df["Total Clicks"].replace(0, pd.NA)
    ).fillna(0)

    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    df["Last Updated (IST)"] = ist_now.strftime("%Y-%m-%d %H:%M:%S")
    df["date"] = date
    return df


# =========================================================
# MAIN PIPELINE ENTRY
# =========================================================

def run_pipeline(report_df, date, gspread_client, mongo_uri):
    sheet = gspread_client.open_by_key(SPREADSHEET_ID)
    mongo_client = MongoClient(mongo_uri)

    raw_domains = load_domains(sheet)
    db_names = [to_db_key(d) for d in raw_domains]
    creds_map = load_mongo_creds(mongo_client, db_names)

    # ---------------- FETCH VIEWS ----------------
    all_views = []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [
            ex.submit(fetch_views, creds_map[d]["uri"], creds_map[d]["db"], date)
            for d in creds_map
        ]
        for fut in as_completed(futures):
            _, _, docs = fut.result()
            all_views.extend(docs)

    views = pd.DataFrame(all_views)

    def write_df(name, df):
        ws = get_or_create_worksheet(sheet, name)
        ws.clear()
        if df.empty:
            ws.update([["(no rows)"]])
            return
        ws.update([df.columns.tolist()] + df.fillna("").astype(str).values.tolist())

    write_df("Views", views)

    views["apiJobId"] = views["apiJobId"].apply(clean_job_id)

    domain_map = dict(zip(views["apiJobId"], views["domain"]))
    company_map = dict(zip(views["apiJobId"], views["company"]))

    report_df["job_id_clean"] = report_df["job_id_clean"].apply(clean_job_id)
    report_df["matched_domain"] = report_df["job_id_clean"].map(domain_map).fillna("UNMATCHED")
    report_df["company"] = report_df["job_id_clean"].map(company_map).fillna("")

    cpa = report_df[report_df["report_type"] == "CPA"].copy()
    cpc = report_df[report_df["report_type"] == "CPC"].copy()

    write_df("cpa_report", cpa)
    write_df("cpc_report", cpc)

    paid_all, unpaid_all = split_paid_unpaid(report_df)
    stats_all = build_stats_for_report(report_df, paid_all, unpaid_all)
    stats_all = add_derived_columns(stats_all, date)

    write_df("Stats", stats_all)

    return {
        "domains": len(creds_map),
        "views": len(views)
    }
