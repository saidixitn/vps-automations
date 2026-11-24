module.exports = {
  apps: [
    {
      name: "Jobiak Dashboard",
      script: "gunicorn",
      args: "--bind 0.0.0.0:8080 --timeout 120 app:app",
      cwd: "/home/jobiak_dashboard",
      interpreter: "/home/jobiak_dashboard/venv/bin/python",
      autorestart: true,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    },
    {
      name: "jobget-api",
      script: "uvicorn",
      args: "main:app --host 0.0.0.0 --port 8000",
      cwd: "/home/jobiak_dashboard",
      interpreter: "/home/jobiak_dashboard/venv/bin/python",
      autorestart: true
    },
    {
      name: "Hourly Dashboard Clicks",
      script: "/home/jobiak_dashboard/daily_stats.py",
      args: "today",
      cwd: "/home/jobiak_dashboard",
      interpreter: "/home/jobiak_dashboard/venv/bin/python",
      cron_restart: "0 * * * *",
      autorestart: false
    },
    {
      name: "Postings Sync",
      script: "/home/jobiak_dashboard/sync_postings.py",
      cwd: "/home/jobiak_dashboard",
      interpreter: "/home/jobiak_dashboard/venv/bin/python",
      cron_restart: "*/30 * * * *",
      autorestart: false
    },
    {
      name: "Banana Clicks Report",
      script: "/home/jobiak_dashboard/run_banana.sh",
      cwd: "/home/jobiak_dashboard",
      cron_restart: "0 11 * * *",
      autorestart: false
    }
  ]
};
