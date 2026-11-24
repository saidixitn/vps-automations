# VPS Automations

A centralized production automation suite and process orchestration system for running background daemons, scheduled telemetry pipelines, domain health monitors, and automated database backups.

---

## What It Is

`vps-automations` is a collection of backend workers and scheduled tasks designed to run on a Linux VPS. It manages automated data extraction, daily metric reporting, database synchronization across distributed MongoDB instances, and proactive alerting for domain and proxy expirations.

Rather than running independent, unmonitored cron scripts directly on the host operating system, all processes are defined declaratively in PM2 ecosystem files. This gives the system centralized process supervision, automatic restarts upon failure, live log rotation, and memory management.

---

## Why It Was Built

Running multiple production pipelines and daily report generators on a VPS without supervision creates significant operational problems:

- Silent script failures: Standard crontabs execute silently; if an unhandled exception or network timeout occurs, it often goes unnoticed until data is missed.
- Configuration sprawl: Database URIs, API keys, and notification emails scattered across individual files make secret rotation and maintenance difficult.
- Lack of centralized observability: Developers must manually SSH into the server and inspect scattered log files to understand current system health.

This repository solves these problems by providing:
1. Declarative Process Control: Every job is tracked, scheduled, and supervised by PM2.
2. Standardized Configuration: Centralized `.env` and service account templates keep code decoupled from environments and credentials.
3. Automated Alerts: Outgoing notifications via SMTP email digests and Telegram bots ensure administrators are proactively informed of renewals and anomalies.
4. Redundant Data Protection: Scheduled MongoDB dumps ensure daily disaster recovery snapshots.

---

## How It Works

The architecture consists of four distinct operational modules:

```
[ PM2 Process Manager ]
        |
        +---> [ Expiration Monitors ]      ---> Alerts via SMTP / Telegram
        |
        +---> [ Daily Telemetry Pipelines ] ---> Syncs to Google Sheets & Email
        |
        +---> [ Management REST API ]       ---> Remote health checks & config
        |
        +---> [ Database Backup Service ]   ---> Automated mongodump archives
```

### 1. Expiration Monitoring
Specialized workers (`domain_expires_new.py`, `proxy_expires.py`, `dc_expires.py`, `pub_expired_check.py`) query database collections to inspect upcoming renewal dates for proxies and web domains. When an asset is within a defined expiration window, formatted alert emails and messages are dispatched.

### 2. Telemetry and Reporting
Reporting scripts (`banana.py`, `stats_email.py`, `updates.py`) aggregate system throughput, clicks, and operational statistics across target dates. The aggregated results are pushed directly to Google Sheets via the Google Sheets API and delivered via HTML email digests twice daily.

### 3. Remote Configuration & Health API
A FastAPI application (`main.py`) running via Uvicorn exposes endpoints to check server status, verify database connectivity, and update connection strings dynamically without requiring manual server restarts.

### 4. Database Backups
Automated backup routines (`backup_script.py`, `auto_git_backup.sh`) capture database collections, compress archives, and sync configurations.

---

## Repository Structure

```
.
|-- .env.example              # Template for all environment variables
|-- credentials.sample.json   # Template for Google service account JSON
|-- ecosystem.config.json     # PM2 multi-process configuration
|-- requirements.txt          # Python runtime dependencies
|-- main.py                   # FastAPI daemon for status and config updates
|-- banana.py                 # Telemetry collector & Google Sheets updater
|-- stats_email.py            # Morning and afternoon email digest generator
|-- updates.py                # Hourly change detection and summary script
|-- domain_expires_new.py     # Domain expiration monitor
|-- proxy_expires.py          # Proxy validity monitor
|-- dc_expires.py             # Client asset expiration worker
|-- dc_expires_mail.py        # Expiration alert email dispatcher
|-- pub_expired_check.py      # Publisher domain expiration validator
|-- new_creds.py              # Credential synchronization daemon
|-- serper.py                 # Google Maps Serper API ingestion worker
|-- scrape_hotels.py          # Entity scraper worker
|-- backup_script.py          # MongoDB backup and archival script
|-- run_banana.sh             # Bash runner for daily telemetry script
|-- run_stats.sh              # Bash runner for daily email digest
|-- auto_git_backup.sh        # Server configuration sync utility
|-- docs/
|   |-- ARCHITECTURE.md       # High-level architecture and system tiers
|   |-- DAEMONS.md            # Complete catalog of PM2 processes and crons
|   `-- SETUP.md              # Installation, environment, and deployment guide
`-- backup_system/
    |-- final_backup.py       # Cloud backup sync script
    `-- client_secrets.sample.json
```

---

## Quickstart

### 1. Install Dependencies

Ensure Python 3.10+ and Node.js with PM2 are installed on the host.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install -g pm2
```

### 2. Configure Environment

```bash
cp .env.example .env
cp credentials.sample.json credentials.json
```

Update `.env` with your MongoDB connection strings, mail server credentials, and Telegram tokens.

### 3. Start Processes

```bash
# Start all processes defined in the ecosystem file
pm2 start ecosystem.config.json

# View live process status
pm2 status

# Inspect real-time logs
pm2 logs
```

---

## Documentation

For in-depth guides, see:
- [System Architecture](docs/ARCHITECTURE.md) - Deep dive into system layers, communication flows, and data boundaries.
- [Daemon Reference](docs/DAEMONS.md) - Process-by-process list of entrypoints, schedules, and log locations.
- [Setup & Deployment](docs/SETUP.md) - Step-by-step instructions for deploying to a fresh server.

---

## License

This project is licensed under the MIT License.
