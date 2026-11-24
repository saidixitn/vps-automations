# Daemon Catalog & Process Schedules

This document describes each process managed by PM2 within `ecosystem.config.json` and standalone config files.

---

## PM2 Service Roster

| Process Name | Entry Point | Execution Mode | Schedule / Trigger | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `jobget-api` | `main.py` | Fork (`uvicorn`) | Persistent (Port 8000) | REST API for remote health checks and dynamic config |
| `mongo-creds-sync` | `new_creds.py` | Fork (`python3`) | Daily (03:30 UTC / 09:00 IST) | Synchronizes database credentials across environments |
| `daily-updates-report` | `updates.py` | Fork (`python3`) | Daily cron | Generates HTML change report across monitored clusters |
| `expiry-earnhaus` | `proxy_expires.py` | Fork (`python3`) | Daily cron | Checks proxy expiration dates and alerts admins |
| `expiry-directclients` | `dc_expires.py` | Fork (`python3`) | Daily cron | Checks client domain expirations and status flags |
| `expiry-newearnhaus` | `newearnhaus_expires.py` | Fork (`python3`) | Daily cron | Validates auxiliary domain renewals |
| `pub-expired-check` | `pub_expired_check.py` | Fork (`python3`) | Daily cron | Publisher domain validity scanner |
| `Expires-Report-Mail` | `dc_expires_mail.py` | Fork (`python3`) | Daily cron | Sends email digest of all upcoming domain and proxy renewals |
| `stats-email-daily` | `run_stats.sh` | Shell wrapper | Twice daily (10:00 AM, 3:00 PM) | Dispatches morning and afternoon operational digests |
| `banana-report` | `run_banana.sh` | Shell wrapper | Daily (11:00 AM) | Collects day-over-day metrics and updates Google Sheets |
| `hotel-scraper` | `scrape_hotels.py` | Fork (`python3`) | On-demand / batch | Ingestion worker for location and entity datasets |
| `Serper API` | `serper.py` | Fork (`python3`) | Scheduled batch | Queries Google Maps Serper endpoints for geo metadata |
| `mongo-daily-backup` | `backup_script.py` | Fork (`python3`) | Nightly (02:00 UTC) | Creates local mongodump archives and cleans old backups |

---

## Log Management

Every process writes standard output (`stdout`) and error logs (`stderr`). By convention, output paths are configured to:

- Standard output: `logs/<process_name>.out.log`
- Standard error: `logs/<process_name>.err.log`

Logs can be viewed live using:
```bash
pm2 logs <process_name>
```
