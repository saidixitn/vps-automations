module.exports = {
  apps: [
    {
      name: "expiry-justopinion",
      script: "/home/dixit/domain_expires_new.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 3 * * *", // 09:00 AM IST
      env: {
        DOMAIN: "justopinionjobs_prod",
        SEMRUSH_DOMAIN: "justopinionjobs.com"
      },
      out_file: "/home/dixit/logs/expiry_justopinion.out.log",
      error_file: "/home/dixit/logs/expiry_justopinion.err.log"
    },
    {
      name: "expiry-v2valuejobs",
      script: "/home/dixit/domain_expires_new.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 3 * * *", // 09:00 AM IST
      env: {
        DOMAIN: "v2valuejobs_prod",
        SEMRUSH_DOMAIN: "v2valuejobs.com"
      },
      out_file: "/home/dixit/logs/expiry_v2valuejobs.out.log",
      error_file: "/home/dixit/logs/expiry_v2valuejobs.err.log"
    },
    {
      name: "expiry-earnwithwfh",
      script: "/home/dixit/domain_expires_new.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 3 * * *", // 09:00 AM IST
      env: {
        DOMAIN: "earnwithwfh_prod",
        SEMRUSH_DOMAIN: "earnwithwfh.com"
      },
      out_file: "/home/dixit/logs/expiry_earnwithwfh.out.log",
      error_file: "/home/dixit/logs/expiry_earnwithwfh.err.log"
    },
    {
      name: "expiry-directclients",
      script: "/home/dixit/dc_expires.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 3 * * *", // 09:00 AM IST
      out_file: "/home/dixit/logs/expiry_dc.out.log",
      error_file: "/home/dixit/logs/expiry_dc.err.log"
    },
    {
      name: "expiry-earnhaus",
      script: "/home/dixit/proxy_expires.py",
      interpreter: "/home/dixit/venv/bin/python",
      autorestart: false,
      cron_restart: "30 3 * * *", // 09:00 AM IST
      out_file: "/home/dixit/logs/expiry_earnhaus.out.log",
      error_file: "/home/dixit/logs/expiry_earnhaus.err.log"
    }
  ]
};
