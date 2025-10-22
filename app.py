# ==============================================================
#  BINTORO ENERGI PERSADA CMMS v3 (Cloud-ready)
#  Developer: ChatGPT (GPT-5)
#  Version: 3.1 — Compatible with GitHub + Supabase + Streamlit Cloud
# ==============================================================

import streamlit as st
import pandas as pd
import os
from datetime import datetime
from supabase import create_client, Client

# ==============================================================
# 🧠 KONFIGURASI SUPABASE
# ==============================================================

# Ambil credential dari Streamlit secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==============================================================
# 🗂️ KONFIGURASI PENYIMPANAN DATA (Auto: Local / Cloud)
# ==============================================================

# Cek apakah sedang berjalan di Streamlit Cloud
if os.getenv("STREAMLIT_RUNTIME") == "true":
    DATA_DIR = "/tmp/data"  # folder temporer di Streamlit Cloud
else:
    DATA_DIR = "data"       # folder lokal

# Buat folder jika belum ada
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    st.warning(f"⚠️ Tidak bisa membuat folder data: {e}")

# ==============================================================
# ⚙️ FUNGSI UTILITAS
# ==============================================================

def save_local_csv(df, filename):
    """Simpan dataframe ke file CSV lokal"""
    file_path = os.path.join(DATA_DIR, filename)
    df.to_csv(file_path, index=False)
    return file_path

def upload_to_supabase(file_path, bucket_name="cmms_backup"):
    """Upload file CSV ke Supabase storage"""
    try:
        with open(file_path, "rb") as f:
            file_name = os.path.basename(file_path)
            supabase.storage.from_(bucket_name).upload(file_name, f)
        st.success(f"✅ File '{file_name}' berhasil di-upload ke Supabase")
    except Exception as e:
        st.error(f"❌ Gagal upload ke Supabase: {e}")

# ==============================================================
# 🧾 FUNGSI INPUT & TAMPILAN DATA
# ==============================================================

def catat_data(kode, nama, spesifikasi, satuan, stok_masuk, stok_keluar):
    """Mencatat data stok masuk/keluar ke Supabase"""
    try:
        now = datetime.now()
        data = {
            "kode_barang": kode,
            "nama_barang": nama,
            "spesifikasi": spesifikasi,
            "satuan": satuan,
            "stok_masuk": stok_masuk,
            "stok_keluar": stok_keluar,
            "tanggal": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        supabase.table("inventory").insert(data).execute()
        st.success("✅ Data berhasil disimpan ke Supabase!")

    except Exception as e:
        st.error(f"❌ Gagal menyimpan data: {e}")

# ==============================================================
# 🧭 ANTARMUKA STREAMLIT
# ==============================================================

st.set_page_config(page_title="CMMS Bintoro Energy Persada", layout="wide")
st.title("🏭 BINTORO ENERGI PERSADA - CMMS Inventory v3")
st.markdown("**Versi Cloud + Supabase + Auto Save**")

tab1, tab2, tab3 = st.tabs(["📦 Input Data", "📊 Data Supabase", "💾 Backup Lokal"])

# ==============================================================
# TAB 1 — INPUT DATA
# ==============================================================

with tab1:
    st.header("📥 Form Input Data Inventory")

    kode = st.text_input("Kode Barang")
    nama = st.text_input("Nama Barang")
    spesifikasi = st.text_area("Spesifikasi")
    satuan = st.text_input("Satuan (misal: pcs, unit, kg)")
    stok_masuk = st.number_input("Stok Masuk", min_value=0)
    stok_keluar = st.number_input("Stok Keluar", min_value=0)

    if st.button("💾 Simpan ke Supabase"):
        if nama:
            catat_data(kode, nama, spesifikasi, satuan, stok_masuk, stok_keluar)
        else:
            st.warning("⚠️ Nama barang wajib diisi!")

# ==============================================================
# TAB 2 — DATA SUPABASE
# ==============================================================

with tab2:
    st.header("📊 Data Inventory dari Supabase")

    try:
        data = supabase.table("inventory").select("*").execute()
        df = pd.DataFrame(data.data)
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Belum ada data di Supabase.")
    except Exception as e:
        st.error(f"Gagal memuat data: {e}")

# ==============================================================
# TAB 3 — BACKUP LOKAL
# ==============================================================

with tab3:
    st.header("💾 Backup CSV Lokal & Upload ke Supabase")

    try:
        data = supabase.table("inventory").select("*").execute()
        df = pd.DataFrame(data.data)

        if not df.empty:
            filename = f"backup_inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            file_path = save_local_csv(df, filename)
            st.success(f"File lokal disimpan di: {file_path}")

            if st.button("☁️ Upload ke Supabase Storage"):
                upload_to_supabase(file_path)
        else:
            st.info("Tidak ada data untuk backup.")
    except Exception as e:
        st.error(f"Gagal membuat backup: {e}")
