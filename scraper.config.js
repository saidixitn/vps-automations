module.exports = {
  apps: [
    {
      name: "hotel-scraper",
      script: "./scrape_hotels.py",
      cwd: "/home/dixit",
      // IMPORTANT: If you created a virtual environment, point to it here. 
      // Otherwise, change this to "python3"
      interpreter: "/home/dixit/venv/bin/python", 
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: "development",
      },
      env_production: {
        NODE_ENV: "production",
      }
    },
    {
      name: "Serper API",
      script: "./serper.py",
      cwd: "/home/dixit",
      // IMPORTANT: If you created a virtual environment, point to it here. 
      // Otherwise, change this to "python3"
      interpreter: "/home/dixit/venv/bin/python", 
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: "development",
      },
      env_production: {
        NODE_ENV: "production",
      }
    }
  ]
};
