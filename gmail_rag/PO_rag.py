import imaplib
import email
from email.header import decode_header
import os
import pandas as pd
import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA

# Email Configuration
IMAP_SERVER = "imap.gmail.com"
PO_DIRECTORY = "po_dumps"
FAISS_INDEX_PATH = "po_faiss_index"

from streamlit import secrets

# Load secrets from .secrets.toml
#secrets_config = secrets.toml_file_config("secrets.toml")
EMAIL_ACCOUNT = st.secrets["EMAIL_ACCOUNT"]
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]

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
                                    print(f"Saved: {filepath}")
        mail.logout()
    except Exception as e:
        print(f"Error: {e}")

# Extract Text from Excel Files
def extract_po_data():
    all_texts = []
    for filename in os.listdir(PO_DIRECTORY):
        if filename.endswith(".xlsx"):
            filepath = os.path.join(PO_DIRECTORY, filename)
            df = pd.read_excel(filepath)
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
    vector_store.save_local(FAISS_INDEX_PATH)
    return vector_store

# Load or Create FAISS Index for PO Dumps
@st.cache_resource
def get_po_vector_store():
    if os.path.exists(FAISS_INDEX_PATH):
        st.info("Loading existing PO FAISS index...")
        return FAISS.load_local(FAISS_INDEX_PATH,
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
