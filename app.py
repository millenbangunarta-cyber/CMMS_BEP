# app_cmms_supabase.py
import streamlit as st
import pandas as pd
from supabase_config import supabase

st.set_page_config(page_title="CMMS BEP - Supabase Version", layout="wide")
st.title("🧰 CMMS Spare Parts Management (Supabase)")

# ============================================================
# 🔧 Fungsi bantu
# ============================================================
def load_spare_parts():
    data = supabase.table("spare_parts").select("*").execute()
    if data.data:
        return pd.DataFrame(data.data)
    else:
        return pd.DataFrame(columns=["kode_barang", "nama_barang", "spesifikasi", "satuan", "available_stock", "minimum_stock"])

def tambah_atau_update_part(kode, nama, spesifikasi, satuan, stok, min_stok):
    existing = supabase.table("spare_parts").select("*").eq("kode_barang", kode).execute()
    if existing.data:
        supabase.table("spare_parts").update({
            "nama_barang": nama,
            "spesifikasi": spesifikasi,
            "satuan": satuan,
            "available_stock": stok,
            "minimum_stock": min_stok
        }).eq("kode_barang", kode).execute()
        st.success(f"✅ Data {kode} berhasil diperbarui.")
    else:
        supabase.table("spare_parts").insert({
            "kode_barang": kode,
            "nama_barang": nama,
            "spesifikasi": spesifikasi,
            "satuan": satuan,
            "available_stock": stok,
            "minimum_stock": min_stok
        }).execute()
        st.success(f"✅ Data {kode} berhasil ditambahkan.")

def hapus_part(kode):
    supabase.table("spare_parts").delete().eq("kode_barang", kode).execute()
    st.warning(f"🗑️ Data {kode} berhasil dihapus.")

# ============================================================
# 🧾 Form input
# ============================================================
st.subheader("➕ Tambah / Update Spare Part")

col1, col2 = st.columns(2)
with col1:
    kode = st.text_input("Kode Barang")
    nama = st.text_input("Nama Barang")
    spesifikasi = st.text_input("Spesifikasi")
with col2:
    satuan = st.text_input("Satuan")
    stok = st.number_input("Available Stock", min_value=0, value=0)
    min_stok = st.number_input("Minimum Stock", min_value=0, value=0)

col3, col4 = st.columns(2)
with col3:
    if st.button("💾 Simpan"):
        if kode and nama:
            tambah_atau_update_part(kode, nama, spesifikasi, satuan, stok, min_stok)
        else:
            st.warning("⚠️ Kode dan Nama Barang wajib diisi!")

with col4:
    if st.button("🗑️ Hapus"):
        if kode:
            hapus_part(kode)
        else:
            st.warning("⚠️ Masukkan Kode Barang yang akan dihapus!")

# ============================================================
# 📋 Tampilkan data
# ============================================================
st.subheader("📦 Data Spare Parts")
df = load_spare_parts()
st.dataframe(df, use_container_width=True)

# ============================================================
# 🔍 Filter dan download
# ============================================================
st.subheader("🔍 Filter Data")
keyword = st.text_input("Cari berdasarkan nama atau kode...")
if keyword:
    df = df[df["nama_barang"].str.contains(keyword, case=False, na=False) | df["kode_barang"].str.contains(keyword, case=False, na=False)]
st.dataframe(df, use_container_width=True)

# ============================================================
# ⚠️ Low Stock Alert
# ============================================================
low_stock = df[df["available_stock"] < df["minimum_stock"]]
if not low_stock.empty:
    st.warning("⚠️ Ada spare part dengan stok di bawah minimum:")
    st.dataframe(low_stock, use_container_width=True)

# ============================================================
# ⬇️ Download CSV
# ============================================================
csv = df.to_csv(index=False).encode("utf-8")
st.download_button("📘 Unduh Data Inventory", csv, "inventory.csv", "text/csv")
