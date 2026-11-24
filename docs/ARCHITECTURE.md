# System Architecture: VPS Automations

## Overview

The `vps-automations` repository houses the production background task infrastructure for server-side operations, data aggregation pipelines, automated health monitors, and daily reporting daemons.

The system relies on three primary tiers:
1. Process Supervison: Node.js PM2 process manager running under systemd.
2. Execution Engine: Python scripts operating inside virtual environments (`venv`).
3. State & Delivery: MongoDB clusters for storage, Google Sheets API for dashboard sync, and SMTP/Telegram for alerts.

---

## Architecture Diagram

```
+-------------------------------------------------------------+
|                          Linux VPS                          |
|                                                             |
|   +-----------------------------------------------------+   |
|   |                  PM2 Process Manager                |   |
|   |                                                     |   |
|   |  - jobget-api (FastAPI / Uvicorn on :8000)          |   |
|   |  - expiry-* (Domain & Proxy expiration monitors)    |   |
|   |  - stats-email-daily (Morning & afternoon reports)  |   |
|   |  - banana-report (Data ingestion & sheets sync)     |   |
|   |  - mongo-daily-backup (Scheduled DB snapshots)      |   |
|   +-----------------------------------------------------+   |
|                              |                              |
|                              v                              |
|   +-----------------------------------------------------+   |
|   |                 Python 3 Runtimes                   |   |
|   |                                                     |   |
|   |  - pymongo (Querying & updating collections)        |   |
|   |  - google-api-python-client (Sheets API)            |   |
|   |  - smtplib (HTML email digest delivery)             |   |
|   |  - requests / serper (External data APIs)           |   |
|   +-----------------------------------------------------+   |
+-------------------------------------------------------------+
                               |
        +----------------------+----------------------+
        |                      |                      |
        v                      v                      v
+---------------+      +---------------+      +---------------+
|    MongoDB    |      | Google Sheets |      | SMTP/Telegram |
|   Clusters    |      | Telemetry Doc |      | Alerts Delivery|
+---------------+      +---------------+      +---------------+
```

---

## Core Functional Subsystems

### 1. Expiration Monitoring Daemons
- `proxy_expires.py`, `domain_expires_new.py`, `newearnhaus_expires.py`, `dc_expires.py`, `pub_expired_check.py`
- Continuously check database collections for upcoming domain and proxy renewal dates.
- Trigger automated notifications via email or Telegram when expiration thresholds (e.g. 7 days, 3 days, 1 day) are reached.

### 2. Telemetry Aggregation & Reporting
- `banana.py`: Pulls operational statistics for a target date, aggregates metrics across multiple MongoDB databases, and writes structured updates into a designated Google Sheet via the Google Sheets API.
- `stats_email.py`: Compiles morning (10:00 AM) and afternoon (3:00 PM) email summaries containing job counts, system throughput, and status flags.
- `updates.py`: Aggregates hourly delta changes across monitored databases and delivers formatted HTML reports to administrators.

### 3. Process API & Remote Configuration
- `main.py`: A lightweight FastAPI service running under Uvicorn that provides an authenticated interface for checking daemon health and updating dynamic database connection strings without restarting the host machine.
- `semrush_api.py`: A FastAPI endpoint allowing external webhooks to trigger keyword analysis jobs on demand.

### 4. Backup & Disaster Recovery
- `backup_script.py`: Automatically dumps specified MongoDB collections into compressed archives.
- `backup_system/final_backup.py`: Uploads compressed database backups to Google Drive using OAuth 2.0 credentials.
- `auto_git_backup.sh`: Periodically stages server configuration snapshots and PM2 process list definitions into a secure repository.
