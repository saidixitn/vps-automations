module.exports = {
  apps: [
    {
      name: "Expires-Report-Mail",
      script: "/home/dixit/dc_expires_mail.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false, // Good for cron jobs
      cron_restart: "15 10 * * *",
      out_file: "/home/dixit/logs/dc_expires_mail.out.log",
      error_file: "/home/dixit/logs/dc_expires_mail.err.log"
    },
  ]
};