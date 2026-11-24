module.exports = {
  apps: [
    {
      name: "universal-expiry",
      script: "/home/dixit/universal_expires.py",
      interpreter: "/home/dixit/venv/bin/python",
      
      // DAEMON MODE:
      // We set autorestart to true so the script stays alive forever.
      // The script itself handles the scheduling (checking every minute).
      autorestart: true,
      cron_restart: null, 

      env: { 
        PYTHONUNBUFFERED: "1",
        TZ: "Asia/Kolkata" // Forces logs and scheduler to use IST
      },
      
      out_file: "/home/dixit/logs/universal_expiry.out.log",
      error_file: "/home/dixit/logs/universal_expiry.err.log"
    }
  ]
};