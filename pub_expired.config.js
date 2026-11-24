module.exports = {
    apps: [
      {
        name: "pub-expired-check",
        script: "/home/dixit/pub_expired_check.py",
        interpreter: "/home/dixit/venv/bin/python",
        autorestart: false, // Good for cron jobs
        cron_restart: "15 10 * * *",
        out_file: "/home/dixit/logs/pub_expired_check.out.log",
        error_file: "/home/dixit/logs/pub_expired_check.err.log"
      },
    ]
  };