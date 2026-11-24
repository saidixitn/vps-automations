module.exports = {
    apps: [
      {
        name: "salary-topicswhiz",
        script: "/home/hari_uva/salary_desc_topicswhiz.py",
        interpreter: "/home/venv/bin/python",
        autorestart: false,
        // Adjust the cron time as needed; currently set to run at 4:00 AM IST
        env: {
          PYTHONUNBUFFERED: "1",
          // Add any specific environment variables for this script here
        },
        out_file: "/home/logs/salary_topicswhiz.out.log",
        error_file: "/home/logs/salary_topicswhiz.err.log"
      }
    ]
  };