# Setup & Deployment Guide

This guide details how to configure and deploy the automation suite on a Linux VPS or local testing environment.

---

## 1. Prerequisites

- Operating System: Ubuntu 20.04+ or Debian 11+ (or macOS/Linux for local testing)
- Python 3.10 or higher
- Node.js 18+ and `pm2` installed globally:
  ```bash
  npm install -g pm2
  ```
- MongoDB instance (local or remote cluster)

---

## 2. Environment Setup

### Clone Repository & Create Virtual Environment

```bash
git clone https://github.com/saidixitn/vps-automations.git
cd vps-automations

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure Environment Variables

Copy the example environment file and provide your credentials:

```bash
cp .env.example .env
```

Key environment variables:
- `MONGO_URI`: Primary MongoDB connection string (e.g. `mongodb://localhost:27017/`)
- `REMOTE_MONGO_URI`: Remote database URI if querying across multiple clusters
- `BANANA_MONGO_URI`: Target database for telemetry metrics
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to your service account JSON file (e.g. `credentials.json`)
- `GOOGLE_SHEET_ID`: Target Google Sheets identifier where reports are pushed
- `SMTP_HOST`: Mail server hostname (e.g. `smtp.gmail.com`)
- `SMTP_PORT`: Port (e.g. `465` for SSL, `587` for TLS)
- `SMTP_USER`: Sender email address
- `SMTP_PASS`: Application-specific password
- `TELEGRAM_BOT_TOKEN`: Telegram bot token for real-time dispatch

### Configure Google Service Account Credentials

If running `banana.py` or Google Sheets integrations:
1. Copy `credentials.sample.json` to `credentials.json`:
   ```bash
   cp credentials.sample.json credentials.json
   ```
2. Replace the placeholder values with your GCP service account private key and client email.
3. Share target Google Sheets with the service account email with `Editor` permissions.

---

## 3. Starting Services with PM2

### Start Entire Suite

To start all configured daemons:
```bash
pm2 start ecosystem.config.json
```

### Start Individual Service

To launch a specific process:
```bash
pm2 start ecosystem.config.json --only jobget-api
```

### Monitoring & Status

Check running processes:
```bash
pm2 status
```

Stream live logs:
```bash
pm2 logs
```

Restart or stop services:
```bash
pm2 restart all
pm2 stop all
```

Ensure PM2 persists across system reboots:
```bash
pm2 save
pm2 startup
```
