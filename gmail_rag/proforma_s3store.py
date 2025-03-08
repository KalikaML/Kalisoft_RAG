#This code automatically fetches Proforma Invoice PDFs from Gmail, saves them locally, uploads them to S3 if not already present

import imaplib
import email
import boto3
import os
import streamlit as st
from email.header import decode_header
import schedule
import time

# Email and S3 credentials
IMAP_SERVER = "imap.gmail.com"
SAVE_DIRECTORY = "proforma_invoice"

from streamlit import secrets

EMAIL_ACCOUNT = st.secrets["EMAIL_ACCOUNT"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]



# S3 Configuration
S3_BUCKET = "kalika-rag"
S3_FOLDER = "proforma_invoice/"
S3_URL = "s3://kalika-rag/proforma_invoice/"

s3_client = boto3.client(
    "s3",
    aws_access_key_id= AWS_ACCESS_KEY,
    aws_secret_access_key= AWS_SECRET_KEY,
)


def clean_filename(filename):
    """Remove unwanted characters from filename."""
    return "".join(c for c in filename if c.isalnum() or c in (".", "_", "-")).strip()


def file_exists_in_s3(filename):
    """Check if file exists in S3 bucket."""
    print(f"Checking if {filename} exists in S3...")
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=S3_FOLDER + filename)
        print(f"File {filename} already exists in S3.")
        return True
    except:
        print(f"File {filename} does NOT exist in S3.")
        return False


def upload_to_s3(filepath, filename):
    """Upload file to S3 if it does not exist."""
    print(f"Attempting to upload {filename} to S3...")
    if not file_exists_in_s3(filename):
        s3_client.upload_file(filepath, S3_BUCKET, S3_FOLDER + filename)
        print(f"Uploaded to S3: {S3_URL}{S3_FOLDER}{filename}")
    else:
        print(f"File already exists in S3: {filename}, skipping upload.")


def download_proforma_pdfs():
    """Download Proforma Invoice PDFs and upload to S3."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        print("Logged in successfully!")

        mail.select("inbox")
        print("Fetching emails with subject 'Proforma Invoice'...")

        status, email_ids = mail.search(None, '(SUBJECT "Proforma Invoice")')

        if status == "OK":
            email_ids = email_ids[0].split()[-10:]  # Get last 10 emails
            print(f"Found {len(email_ids)} emails.")

            os.makedirs(SAVE_DIRECTORY, exist_ok=True)

            for e_id in email_ids:
                print(f"Processing email ID: {e_id}")
                status, msg_data = mail.fetch(e_id, "(RFC822)")

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        for part in msg.walk():
                            if part.get_content_disposition() == "attachment":
                                filename = part.get_filename()
                                if filename and filename.lower().endswith(".pdf"):
                                    filename = decode_header(filename)[0][0]
                                    if isinstance(filename, bytes):
                                        filename = filename.decode()

                                    cleaned_filename = clean_filename(filename)
                                    filepath = os.path.join(SAVE_DIRECTORY, cleaned_filename)

                                    if not os.path.exists(filepath):
                                        print(f"Downloading: {cleaned_filename}")
                                        with open(filepath, "wb") as f:
                                            f.write(part.get_payload(decode=True))
                                        print(f"Saved locally: {filepath}")

                                        # Upload to S3
                                        upload_to_s3(filepath, cleaned_filename)
                                    else:
                                        print(f"File already exists locally: {filepath}, skipping download.")
        else:
            print("No matching emails found.")

        mail.logout()
        print("Proforma Invoice PDFs processed successfully!")

    except Exception as e:
        print(f"Error: {e}")


download_proforma_pdfs()
# Scheduler to run the function daily
"""schedule.every().day.at("00:00").do(download_proforma_pdfs)

if __name__ == "__main__":
    print("Scheduler started! Running email processing daily at midnight.")
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute
"""
