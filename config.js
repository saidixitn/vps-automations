{
  name: "mongo-creds-sync",
  script: "/home/dixit/new_creds.py",
  interpreter: "/home/dixit/venv/bin/python",
  autorestart: false,
  cron_restart: "30 3 * * *", // 03:30 UTC is 09:00 AM IST
  out_file: "/home/dixit/logs/mongo_creds_sync.out.log",
  error_file: "/home/dixit/logs/mongo_creds_sync.err.log",
  log_date_format: "YYYY-MM-DD HH:mm:ss"
}
