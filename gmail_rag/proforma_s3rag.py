#This code fetches Proforma Invoice emails, extracts text from PDFs, indexes data using FAISS and HuggingFace embeddings, store files in AWS S3
#  and enables querying via Llama2 in a Streamlit RAG system.

import imaplib
import email
from email.header import decode_header
import os
import re
import boto3
import faiss
import tempfile
import numpy as np
import streamlit as st
import pdfplumber
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings  # Corrected Import
from langchain_community.vectorstores import FAISS
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA

# Email Configuration
IMAP_SERVER = "imap.gmail.com"
SAVE_DIRECTORY = "proforma_pdfs"
S3_BUCKET_NAME = "kalika-rag"
FAISS_INDEX_PATH = "proforma_faiss_index.index"
FAISS_INDEX_PATH_S3 = "s3://kalika-rag/faiss_indexes/"  
# Load credentials from Streamlit secrets
from streamlit import secrets

EMAIL_ACCOUNT = st.secrets["EMAIL_ACCOUNT"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]

# Initialize S3 Client
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
)

# Utility: Clean filenames
def clean_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]

# Download Proforma Invoice PDFs
def download_proforma_pdfs():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")

        status, email_ids = mail.search(None, '(SUBJECT "Proforma Invoice")')

        if status == "OK":
            email_ids = email_ids[0].split()[-10:]  # Get last 10 emails
            os.makedirs(SAVE_DIRECTORY, exist_ok=True)

            for e_id in email_ids:
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

                                    with open(filepath, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                        print(f"Saved: {filepath}")
        mail.logout()
    except Exception as e:
        st.error(f"Error: {e}")

# Extract text from PDFs
def extract_proforma_text(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

# Process Proforma PDFs
def process_proforma_documents():
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    all_texts = []
    
    for filename in os.listdir(SAVE_DIRECTORY):
        filepath = os.path.join(SAVE_DIRECTORY, filename)
        if filename.endswith(".pdf"):
            text = extract_proforma_text(filepath)
            all_texts.extend(text_splitter.split_text(text))

    return all_texts

# Upload FAISS index to S3
def upload_faiss_to_s3():
    if os.path.exists(FAISS_INDEX_PATH):
        with open(FAISS_INDEX_PATH, "rb") as f:
            s3_client.upload_fileobj(f, S3_BUCKET_NAME, FAISS_INDEX_PATH_S3)
        st.success("FAISS index uploaded to S3 successfully.")

# Download FAISS index from S3
def download_faiss_from_s3():
    try:
        s3_client.download_file(S3_BUCKET_NAME, FAISS_INDEX_PATH_S3, FAISS_INDEX_PATH)
        return True
    except Exception:
        return False

# Create FAISS Vector Store
def create_proforma_vector_store(documents):
    if not documents:
        st.warning("No proforma invoice data found!")
        return None

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vector_store = FAISS.from_texts(documents, embeddings)

    global FAISS_INDEX_PATH  # Ensure we modify the global variable

    try:
        # Try writing FAISS index to the current directory
        faiss.write_index(vector_store.index, FAISS_INDEX_PATH)
    except RuntimeError:
        # If permission is denied, use a temporary directory
        temp_index_path = os.path.join(tempfile.gettempdir(), "faiss_index.index")
        faiss.write_index(vector_store.index, temp_index_path)
        FAISS_INDEX_PATH = temp_index_path  # Update the global path
        st.warning(f"Permission denied for saving in the current directory. Using temp path: {FAISS_INDEX_PATH}")

    return vector_store

# Load or Create FAISS Index
@st.cache_resource
def get_proforma_vector_store():
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    
    if download_faiss_from_s3():
        st.info("Loaded FAISS index from S3.")
        index = faiss.read_index(FAISS_INDEX_PATH)
        return FAISS(index=index, embeddings=embeddings)
    
    # If S3 index is not available, process documents and create new index
    documents = process_proforma_documents()
    return create_proforma_vector_store(documents)

# Query RAG Model for Proforma Invoice Data
def query_proforma_rag(query):
    vector_store = get_proforma_vector_store()
    if not vector_store:
        return "Index not found. Please build the index first."

    retriever = vector_store.as_retriever()
    llm = Ollama(model="llama2:latest")  # Using Llama2
    chain = RetrievalQA.from_chain_type(llm, retriever=retriever)
    
    return chain.run(query)

# Streamlit UI
st.title("RAG System for Proforma Invoice Analysis")

# Automatically Download & Process Emails on App Load
download_proforma_pdfs()
documents = process_proforma_documents()
create_proforma_vector_store(documents)

# Query Input
query = st.text_input("Enter your query about Proforma Invoices:")
if query:
    answer = query_proforma_rag(query)
    st.write("Answer:", answer)
