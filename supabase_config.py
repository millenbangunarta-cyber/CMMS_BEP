# supabase_config.py
from supabase import create_client
import streamlit as st

# Ambil credential dari Streamlit Secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# Buat koneksi ke Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
