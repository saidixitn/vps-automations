module.exports = {
  apps: [
    // --- 1. Mongo Creds Sync (06:00 AM IST) ---
    {
      name: "mongo-creds-sync",
      script: "/home/dixit/new_creds.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 0 * * *", // 00:30 UTC is 06:00 AM IST
      out_file: "/home/dixit/logs/mongo_creds_sync.out.log",
      error_file: "/home/dixit/logs/mongo_creds_sync.err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    },

    // --- 2. Daily Updates Report (09:20 AM IST) ---
    {
      name: "daily-updates-report",
      script: "/home/dixit/updates.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "50 3 * * *", // 03:50 UTC is 09:20 AM IST
      out_file: "/home/dixit/logs/updates.out.log",
      error_file: "/home/dixit/logs/updates.err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    }
  ]
};
