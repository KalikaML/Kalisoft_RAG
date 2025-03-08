#This code builds a Streamlit-based RAG system that fetches PO emails, extracts data, 
# indexes it with FAISS, store files in AWS S3 and enables querying via Llama2.


import imaplib
import email
from email.header import decode_header
import os
import boto3
import pandas as pd
import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
import tempfile

# AWS S3 Configuration
S3_BUCKET_NAME = "kalika-rag"
S3_FAISS_INDEX_PATH = "faiss_indexes/po_faiss_index"

# Email Configuration
IMAP_SERVER = "imap.gmail.com"
PO_DIRECTORY = "po_dumps"

# Load secrets from Streamlit
from streamlit import secrets

EMAIL_ACCOUNT = st.secrets["EMAIL_ACCOUNT"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]

# Initialize S3 Client
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

# Utility: Clean filenames
def clean_filename(filename):
    return filename.replace(" ", "_").replace("/", "_")

# Download PO Dump Emails and Save to Excel
def download_po_dump():
    os.makedirs(PO_DIRECTORY, exist_ok=True)
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

                                    filepath = os.path.join(PO_DIRECTORY, clean_filename(filename))
                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    
                                    # Upload to S3
                                    s3_key = f"po_dumps/{clean_filename(filename)}"
                                    s3_client.upload_file(filepath, S3_BUCKET_NAME, s3_key)
                                    print(f"Uploaded to S3: {s3_key}")
        mail.logout()
    except Exception as e:
        print(f"Error: {e}")

# Extract Text from Excel Files
def extract_po_data():
    all_texts = []
    
    # Download PO dumps from S3
    s3_paginator = s3_client.get_paginator("list_objects_v2")
    response = s3_paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix="po_dumps/")
    
    for page in response:
        if "Contents" in page:
            for obj in page["Contents"]:
                s3_key = obj["Key"]
                filename = os.path.basename(s3_key)
                temp_filepath = os.path.join(tempfile.gettempdir(), filename)
                
                # Download from S3
                s3_client.download_file(S3_BUCKET_NAME, s3_key, temp_filepath)
                
                # Read Excel
                df = pd.read_excel(temp_filepath)
                text = df.to_string()
                all_texts.append(text)

    print(f"Extracted {len(all_texts)} text chunks from PO dumps.")
    return all_texts

# Create FAISS Vector Store
def create_po_vector_store(documents):
    if not documents:
        st.warning("No PO dump data found!")
        return None
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vector_store = FAISS.from_texts(documents, embeddings)

    # Save FAISS index to temp file
    temp_faiss_path = os.path.join(tempfile.gettempdir(), "faiss_index")
    vector_store.save_local(temp_faiss_path)

    # Upload FAISS index to S3
    for file in os.listdir(temp_faiss_path):
        s3_key = f"{S3_FAISS_INDEX_PATH}/{file}"
        s3_client.upload_file(os.path.join(temp_faiss_path, file), S3_BUCKET_NAME, s3_key)
        print(f"Uploaded FAISS index to S3: {s3_key}")

    return vector_store

# Load or Create FAISS Index for PO Dumps
@st.cache_resource
def get_po_vector_store():
    temp_faiss_path = os.path.join(tempfile.gettempdir(), "faiss_index")
    
    # Download FAISS index from S3
    s3_paginator = s3_client.get_paginator("list_objects_v2")
    response = s3_paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_FAISS_INDEX_PATH)

    os.makedirs(temp_faiss_path, exist_ok=True)
    
    for page in response:
        if "Contents" in page:
            for obj in page["Contents"]:
                s3_key = obj["Key"]
                filename = os.path.basename(s3_key)
                s3_client.download_file(S3_BUCKET_NAME, s3_key, os.path.join(temp_faiss_path, filename))
                print(f"Downloaded FAISS index from S3: {s3_key}")

    if os.path.exists(temp_faiss_path):
        st.info("Loading existing PO FAISS index from S3...")
        return FAISS.load_local(temp_faiss_path,
                                HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
                                allow_dangerous_deserialization=True)
    
    documents = extract_po_data()
    return create_po_vector_store(documents)

# Query RAG Model for PO Dump Data
def query_po_rag(query):
    vector_store = get_po_vector_store()
    if not vector_store:
        return "Index not found. Please build the index first."
    
    retriever = vector_store.as_retriever()
    llm = Ollama(model="llama2:latest")  # Using Llama2
    chain = RetrievalQA.from_chain_type(llm, retriever=retriever)
    
    return chain.run(query)

# Streamlit UI
st.title("RAG System for PO Dump Analysis")

download_po_dump()
documents = extract_po_data()
create_po_vector_store(documents)

query = st.text_input("Enter your query about PO Orders:")
if query:
    answer = query_po_rag(query)
    st.write("Answer:", answer)
