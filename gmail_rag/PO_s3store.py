#This code fetches PO order emails, downloads Excel attachments, saves them locally, and uploads them to AWS S3 if not already present.

import os
import imaplib
import email
import boto3
import streamlit as st
from email.header import decode_header

# Email and S3 credentials
IMAP_SERVER = "imap.gmail.com"
SAVE_DIRECTORY = "PO_Dump"

from streamlit import secrets

EMAIL_ACCOUNT = st.secrets["EMAIL_ACCOUNT"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY= st.secrets["AWS_SECRET_KEY"]

# S3 Configuration
S3_BUCKET = "kalika-rag"  
S3_FOLDER = "PO_Dump/"  
S3_URL = "s3://kalika-rag/PO_Dump/"

s3_client = boto3.client(
    "s3",
    aws_access_key_id= AWS_ACCESS_KEY,
    aws_secret_access_key= AWS_SECRET_KEY,
)

def clean_filename(filename):
    """Sanitize filename to prevent path traversal issues."""
    return "".join(c if c.isalnum() or c in (".", "_") else "_" for c in filename)

def file_exists_in_s3(bucket, key):
    """Check if a file exists in S3."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def upload_to_s3(local_path, bucket, s3_key):
    """Upload file to S3 if it doesn't already exist."""
    if not file_exists_in_s3(bucket, s3_key):
        s3_client.upload_file(local_path, bucket, s3_key)
        print(f"Uploaded to S3: {s3_key}")
    else:
        print(f"File already exists in S3: {s3_key}, skipping upload.")

def download_po_dump():
    """Download PO Order emails, save Excel attachments locally, and upload to S3."""
    os.makedirs(SAVE_DIRECTORY, exist_ok=True)
    
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")

        status, email_ids = mail.search(None, '(SUBJECT "PO Order")')

        if status == "OK":
            email_ids = email_ids[0].split()[-10:]  # Get last 10 emails
            for e_id in email_ids:
                status, msg_data = mail.fetch(e_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        for part in msg.walk():
                            if part.get_content_disposition() == "attachment":
                                filename = part.get_filename()
                                if filename and filename.endswith(".xlsx"):
                                    filename = decode_header(filename)[0][0]
                                    if isinstance(filename, bytes):
                                        filename = filename.decode()

                                    filename = clean_filename(filename)
                                    local_filepath = os.path.join(SAVE_DIRECTORY, filename)
                                    s3_key = f"{S3_FOLDER}{filename}"

                                    if not os.path.exists(local_filepath):  # Avoid re-downloading
                                        with open(local_filepath, "wb") as f:
                                            f.write(part.get_payload(decode=True))
                                        print(f"Saved locally: {local_filepath}")
                                    
                                    upload_to_s3(local_filepath, S3_BUCKET , s3_key)
        mail.logout()
    except Exception as e:
        print(f"Error: {e}")

# Run the function
download_po_dump()
