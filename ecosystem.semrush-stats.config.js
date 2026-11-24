module.exports = {
  apps: [
    {
      name: "semrush-job-stats",

      script: "/home/dixit/semrush_job_stats.py",
      interpreter: "/home/dixit/venv/bin/python",

      exec_mode: "fork",
      instances: 1,

      // batch job
      autorestart: false,

      // run daily at 02:30 UTC
      cron_restart: "30 2 * * *",

      env: {
        PYTHONUNBUFFERED: "1",
        TZ: "UTC"
      },

      out_file: "/home/dixit/logs/semrush_job_stats.out.log",
      error_file: "/home/dixit/logs/semrush_job_stats.err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss"
    }
  ]
};
