import imaplib
import email
from email.header import decode_header
import os
import datetime
import re
import faiss
import numpy as np
import streamlit as st
import pdfplumber
import pandas as pd
from docx import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA

# Email Configuration
IMAP_SERVER = "imap.gmail.com"
SAVE_DIRECTORY = "proforma_pdfs"
FAISS_INDEX_PATH = "proforma_faiss_index"
DOCUMENT_EXTENSIONS = {".pdf"}

from streamlit import secrets

# Load secrets from .secrets.toml
#secrets_config = secrets.toml_file_config("secrets.toml")
EMAIL_ACCOUNT = st.secrets["gmail_uname"]
EMAIL_PASSWORD = st.secrets["gmail_pwd"]



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

                                    if not os.path.exists(filepath):
                                        with open(filepath, "wb") as f:
                                            f.write(part.get_payload(decode=True))
                                        st.write(f"Saved: {filepath}")
                                    else:
                                        st.write(f"File already exists: {filepath}, skipping download.")
        mail.logout()
        print("Proforma Invoice PDFs downloaded successfully!")
    except Exception as e:
        print(f"Error: {e}")

# Extract Key Data from PDFs
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

    print(f"Extracted {len(all_texts)} text chunks from proforma invoices.")
    return all_texts

# Create FAISS Vector Store for Proforma PDFs
def create_proforma_vector_store(documents):
    if not documents:
        st.warning("No proforma invoice data found!")
        return None

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vector_store = FAISS.from_texts(documents, embeddings)
    vector_store.save_local(FAISS_INDEX_PATH)
    return vector_store

# Load or Create FAISS Index for Proforma Invoices
@st.cache_resource
def get_proforma_vector_store():
    if os.path.exists(FAISS_INDEX_PATH):
        st.info("Loading existing Proforma FAISS index...")
        return FAISS.load_local(FAISS_INDEX_PATH,
                                HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
                                allow_dangerous_deserialization=True)
    
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

download_proforma_pdfs()
documents = process_proforma_documents()
create_proforma_vector_store(documents)

query = st.text_input("Enter your query about Proforma Invoices:")
if query:
    answer = query_proforma_rag(query)
    st.write("Answer:", answer)
