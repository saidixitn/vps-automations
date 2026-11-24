from fastapi import FastAPI
import subprocess
import os
from dotenv import load_dotenv
load_dotenv()
app = FastAPI(title="SEMRUSH API")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/run")
def run_job():
    subprocess.Popen([
        "/home/dixit/venvs/semrush/bin/python",
        "/home/dixit/semrush_job_stats.py"
    ])
    return {"started": True}
