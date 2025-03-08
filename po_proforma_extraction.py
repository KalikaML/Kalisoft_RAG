import imaplib
import email
import boto3
import os
from email.header import decode_header
from io import BytesIO  # For handling attachments in memory
import streamlit as st

# Email and S3 credentials
IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = st.secrets["gmail_uname"]
EMAIL_PASSWORD = st.secrets["gmail_pwd"]


# S3 Configuration
S3_BUCKET = "kalika-rag"
S3_PO_FOLDER = "PO_Dump/"  # Folder for PO Dump PDFs
S3_PROFORMA_FOLDER = "proforma_invoice/"  # Folder for Proforma Invoice PDFs

# AWS Credentials (Set these as environment variables)
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")

# Initialize S3 client
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
)


def clean_filename(filename):
    """Remove unwanted characters from filename."""
    return "".join(c for c in filename if c.isalnum() or c in (".", "_", "-")).strip()


def file_exists_in_s3(s3_folder, filename):
    """Check if file exists in S3 bucket."""
    s3_key = s3_folder + filename
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"✅ File {filename} already exists in S3.")
        return True
    except:
        print(f"🔍 File {filename} does NOT exist in S3.")
        return False


def upload_to_s3(file_data, s3_folder, filename):
    """Upload file to S3 if it does not exist."""
    s3_key = s3_folder + filename

    if not file_exists_in_s3(s3_folder, filename):
        print(f"🚀 Uploading {filename} to S3 ({s3_folder})...")
        s3_client.upload_fileobj(BytesIO(file_data), S3_BUCKET, s3_key)
        print(f"✅ Successfully uploaded to s3://{S3_BUCKET}/{s3_key}")
    else:
        print(f"⏭️ Skipping upload. File {filename} already exists in S3.")


def process_email_attachments(subject_filter, s3_folder):
    """Process emails and upload PDF attachments to S3."""
    try:
        print(f"\n🔄 Connecting to email server for '{subject_filter}' emails...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        print(f"📥 Logged in successfully and searching for '{subject_filter}' emails...")

        # Search for emails with the specified subject
        status, email_ids = mail.search(None, f'(SUBJECT "{subject_filter}")')

        if status != "OK" or not email_ids[0]:
            print(f"⚠️ No '{subject_filter}' emails found.")
            return

        email_ids = email_ids[0].split()[-10:]  # Process last 10 emails
        print(f"📩 Found {len(email_ids)} emails to process.")

        for e_id in email_ids:
            print(f"\n📬 Processing email ID: {e_id}...")
            status, msg_data = mail.fetch(e_id, "(RFC822)")

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    for part in msg.walk():
                        if part.get_content_disposition() == "attachment":
                            filename = part.get_filename()

                            if filename:
                                decoded_header = decode_header(filename)
                                decoded_filename, encoding = decoded_header[0]

                                if isinstance(decoded_filename, bytes):
                                    decoded_filename = decoded_filename.decode(encoding or "utf-8")

                                filename = clean_filename(decoded_filename)

                                print(f"📎 Found attachment: {filename}")

                                file_data = part.get_payload(decode=True)
                                if not file_data:
                                    print("⚠️ Attachment data is empty. Skipping file.")
                                    continue

                                upload_to_s3(file_data, s3_folder, filename)

        mail.logout()
        print(f"\n✅ Finished processing '{subject_filter}' emails!")

    except Exception as e:
        print(f"❌ ERROR while processing '{subject_filter}': {e}")


# Run both processes
process_email_attachments("Proforma Invoice", S3_PROFORMA_FOLDER)
process_email_attachments("PO Dump", S3_PO_FOLDER)
