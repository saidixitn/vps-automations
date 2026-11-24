module.exports = {
  apps: [
    {
      name: "semrush-import",

      script: "/home/dixit/semrush_import.py",
      interpreter: "/home/dixit/venv/bin/python",

      exec_mode: "fork",
      instances: 1,

      // Batch job (NOT a server)
      autorestart: false,

      // Runs daily at 02:30 UTC
      cron_restart: "30 2 * * *",

      env: {
        PYTHONUNBUFFERED: "1",
        TZ: "UTC"
      },

      out_file: "/home/dixit/logs/semrush_import.out.log",
      error_file: "/home/dixit/logs/semrush_import.err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    }
  ]
};

