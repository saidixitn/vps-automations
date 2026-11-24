import pymongo
import pandas as pd
from datetime import datetime, timedelta, timezone
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import io
import os
from dotenv import load_dotenv
load_dotenv()
# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
LOCAL_MONGO_URI =  os.getenv("MONGO_URI")
if not LOCAL_MONGO_URI:
    raise Exception("LOCAL_MONGO_URI not found in environment variables") 
LOCAL_DB = "domain_expires"

COLLECTIONS_TO_CHECK = [
    "apexfocusgroup_expires",
  #  "newearnhaus_expires",
    "levelsurveys_expires"
]

LIMIT = 2000
DAYS_AGO = 10

# Email Config
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_SENDER = "saidixitn@gmail.com"
SMTP_RECEIVER = "saidixitn@gmail.com"
SMTP_CC = "tarunteja.palla@jobiak.com"
SMTP_APP_PASSWORD = os.getenv("SMTP_PASS")       # Gmail App Password
if not SMTP_APP_PASSWORD:
    raise Exception("SMTP_APP_PASSWORD not found in environment variables") 

# --------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------
if __name__ == "__main__":
    print("\n========== IN-MEMORY EXPORT & EMAIL SCRIPT STARTING ==========\n")

    # 1. Calculate Target Date (10 days ago from today)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DAYS_AGO)
    print(f"Target Cutoff Date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # 2. Connect to Local MongoDB
    client = pymongo.MongoClient(LOCAL_MONGO_URI)
    db = client[LOCAL_DB]

    sheets_data = {}

    # 3. Query Collections
    for coll_name in COLLECTIONS_TO_CHECK:
        print(f"Querying {coll_name}...")

        pipeline = {
            "gpost_date": {
                "$lte": cutoff_date
            }
        }

        # Fetch data with limit
        cursor = db[coll_name].find(pipeline).limit(LIMIT)
        docs = list(cursor)

        if not docs:
            print(f"  -> No records found older than 10 days in '{coll_name}'. Skipping sheet.")
            continue

        print(f"  -> Found {len(docs)} records for '{coll_name}'.")

        # Convert to DataFrame
        df = pd.DataFrame(docs)

        if '_id' in df.columns:
            df['_id'] = df['_id'].astype(str)

        for col in df.select_dtypes(include=['datetimetz']).columns:
            df[col] = df[col].dt.tz_localize(None)

        sheet_name = coll_name.replace("_expires", "")
        sheets_data[sheet_name] = df

    # 4. Generate Excel File in Memory
    if not sheets_data:
        print("\nNo data found across any collections matching the criteria. Exiting without sending email.")
        exit()

    # Generate the requested filename format
    now = datetime.now()
    excel_filename = f"DC_Expires_{now.strftime('%b')}_{now.strftime('%d')}.xlsx"

    print(f"\nWriting data to in-memory buffer for {excel_filename}...")

    # Use io.BytesIO() to hold the Excel data in RAM instead of on the hard drive
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        for sheet_name, df in sheets_data.items():
            df.to_excel(writer, index=False, sheet_name=sheet_name)

    print("In-memory Excel file generated successfully.")

    # 5. Send Email
    print("\nPreparing to send email...")

    msg = MIMEMultipart()
    msg['From'] = SMTP_SENDER
    msg['To'] = SMTP_RECEIVER
    msg['Cc'] = SMTP_CC
    msg['Subject'] = f"Automated Expired Jobs Report - {now.strftime('%Y-%m-%d')}"

    body = (
        f"Hi Team,\n\n"
        f"Please find attached the expired jobs report for {now.strftime('%Y-%m-%d')}.\n\n"
        f"Criteria applied:\n"
        f"- gpost_date <= {cutoff_date.strftime('%Y-%m-%d')}\n"
        f"- Limit: {LIMIT} records per client\n\n"
        f"Clients included in this attachment:\n"
    )
    for sheet in sheets_data.keys():
        body += f"- {sheet}\n"

    body += "\nBest regards,\nAutomated System"

    msg.attach(MIMEText(body, 'plain'))

    # Attach the in-memory Excel file
    try:
        # We use the buffer's value directly instead of reading from a file
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(excel_buffer.getvalue())

        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename={excel_filename}")
        msg.attach(part)

        # SMTP Setup and dispatch
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_SENDER, SMTP_APP_PASSWORD)

        recipients = [SMTP_RECEIVER, SMTP_CC]
        server.sendmail(SMTP_SENDER, recipients, msg.as_string())
        server.quit()

        print(f"Email successfully sent to {SMTP_RECEIVER} and CC'd to {SMTP_CC}.")

    except Exception as e:
        print(f"Error sending email: {e}")

    # Close the memory buffer to free up RAM
    excel_buffer.close()

    print("\n========== SCRIPT COMPLETE ==========\n")