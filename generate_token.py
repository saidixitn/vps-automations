import os
from google_auth_oauthlib.flow import InstalledAppFlow

# This must match the scope in your VPS script
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def generate_new_token():
    print("Opening browser for Google Authentication...")
    # This assumes client_secrets.json is in the same folder
    flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', SCOPES)
    
    # This will open your web browser to log in
    creds = flow.run_local_server(port=0)
    
    # Save the credentials as a proper JSON string
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        
    print("\nSUCCESS! A valid, plain-text 'token.json' has been created.")
    print("Upload this new 'token.json' to your VPS at /home/dixit/backup_system/")

if __name__ == '__main__':
    generate_new_token()
