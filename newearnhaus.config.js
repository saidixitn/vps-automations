module.exports = {
    apps: [
      {
        name: "expiry-newearnhaus",
        script: "/home/dixit/newearnhaus_expires.py",
        interpreter: "/home/dixit/venv/bin/python",
        autorestart: false,
        cron_restart: "30 4 * * *",
        out_file: "/home/dixit/logs/newearnhaus_expires.out.log",
        error_file: "/home/dixit/logs/newearnhaus_expires.err.log"
      },
    ]
  };
  