# app_cmms_supabase.py
# ==============================================================#
#  BINTORO ENERGI PERSADA CMMS v3 (Cloud-ready)                 #
#  Developer: ChatGPT (GPT-5 Thinking mini)                    #
#  Date: 2025-10-22 (adapted)                                   #
# ==============================================================#

import os
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time as dtime
from io import BytesIO
import base64
import sqlite3
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

# Try to import supabase client from local config; fallback to env vars
try:
    from supabase_config import supabase  # user-provided config (preferred)
except Exception:
    # Try to create client from env variables
    try:
        from supabase import create_client
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        if SUPABASE_URL and SUPABASE_KEY:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        else:
            supabase = None
    except Exception:
        supabase = None

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="BINTORO ENERGI PERSADA CMMS",
                   page_icon="🛠️",
                   layout="wide")

# Force "dark" look with a small CSS tweak (works on many Streamlit deployments)
st.markdown(
    """
    <style>
    .css-1d391kg {background-color: #0e1117;}  /* page background (may vary by version) */
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stButton>button { border-radius: 8px; }
    /* Make tables look better in dark */
    .dataframe td, .dataframe th { color: #e6eef6 !important; }
    .stMarkdown, .stText { color: #e6eef6; }
    </style>
    """,
    unsafe_allow_html=True
)

ROOT_DIR = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
DB_PATH = os.path.join(ROOT_DIR, "cmms.db")  # kept for local fallback / backups
UPLOAD_DIR = os.path.join(ROOT_DIR, "uploads")
LOGO_PATH = os.path.join(UPLOAD_DIR, "logo_bep.jpg")
DATA_DIR = os.path.join(ROOT_DIR, "data")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# =========================
# HELPERS: Local DB (light usage) & Supabase wrappers
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def run_local_query(query, params=(), fetch=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    if fetch:
        data = cur.fetchall()
        conn.close()
        return data
    conn.close()

def fetch_local_df(query, params=()):
    conn = get_conn()
    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df

# Supabase helpers (safe checks)
def sb_table_select(table_name, columns="*", filters=None):
    """
    filters: list of tuples (col, op, val) e.g. [("kode_barang","eq","ABC")]
    Returns DataFrame (empty if no connection or no rows)
    """
    if supabase is None:
        return pd.DataFrame()
    try:
        builder = supabase.table(table_name).select(columns)
        if filters:
            for col, op, val in filters:
                builder = getattr(builder, op)(col, val)
        res = builder.execute()
        data = res.data if hasattr(res, "data") else res
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Supabase error: {e}")
        return pd.DataFrame()

def sb_table_upsert(table_name, payload):
    if supabase is None:
        return False, "No supabase client"
    try:
        res = supabase.table(table_name).upsert(payload).execute()
        return True, res
    except Exception as e:
        return False, str(e)

def sb_table_insert(table_name, payload):
    if supabase is None:
        return False, "No supabase client"
    try:
        res = supabase.table(table_name).insert(payload).execute()
        return True, res
    except Exception as e:
        return False, str(e)

def sb_table_update(table_name, payload, match_col, match_val):
    if supabase is None:
        return False, "No supabase client"
    try:
        res = supabase.table(table_name).update(payload).eq(match_col, match_val).execute()
        return True, res
    except Exception as e:
        return False, str(e)

def sb_table_delete(table_name, match_col, match_val):
    if supabase is None:
        return False, "No supabase client"
    try:
        res = supabase.table(table_name).delete().eq(match_col, match_val).execute()
        return True, res
    except Exception as e:
        return False, str(e)

# =========================
# UTILS: PDF / Excel / CSV helpers & misc
# =========================
def generate_pdf_report(title, df, file_name="report.pdf"):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    if os.path.exists(LOGO_PATH):
        try:
            c.drawImage(LOGO_PATH, 2 * cm, height - 3 * cm, width=3 * cm, preserveAspectRatio=True)
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 16)
    c.drawString(6 * cm, height - 2.5 * cm, title)
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 3.5 * cm, datetime.now().strftime("Tanggal Cetak: %d-%m-%Y %H:%M"))
    x, y = 2 * cm, height - 4.5 * cm
    c.setFont("Helvetica", 9)
    # header
    col_width = (width - 4 * cm) / max(1, len(df.columns))
    for col in df.columns:
        c.drawString(x, y, str(col)[:20])
        x += col_width
    y -= 0.6 * cm
    x = 2 * cm
    # rows
    for _, row in df.iterrows():
        for val in row:
            c.drawString(x, y, str(val)[:30])
            x += col_width
        x = 2 * cm
        y -= 0.5 * cm
        if y < 2 * cm:
            c.showPage()
            y = height - 4 * cm
    c.save()
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode()
    href = f'<a href="data:application/pdf;base64,{b64}" download="{file_name}">📄 Unduh PDF</a>'
    return href

def to_excel_bytes(df, sheet_name="Sheet1"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def to_excel_download_button(df, filename="data.xlsx", sheet_name="Sheet1", label="Download Excel"):
    processed_data = to_excel_bytes(df, sheet_name=sheet_name)
    b64 = base64.b64encode(processed_data).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">{label}</a>'
    st.markdown(href, unsafe_allow_html=True)

def save_backup_csv(df, filename):
    path = os.path.join(DATA_DIR, filename)
    df.to_csv(path, index=False)
    return path

# =========================
# DATA LAYER: Spare parts, Work orders, Activity
# =========================
def load_spare_parts():
    """Load spare_parts from Supabase (or return empty df)"""
    df = sb_table_select("spare_parts", "*")
    if df.empty:
        st.info("Belum ada data spare parts di Supabase.")
        return pd.DataFrame(columns=["id","kode_barang","nama_barang","spesifikasi","available_stock","minimum_stock","satuan"])
    return df

def tambah_atau_update_part(kode, nama, spesifikasi, satuan, stok, min_stok):
    """Insert or update spare part by kode_barang"""
    if not kode or not nama:
        st.warning("Kode dan Nama Barang wajib diisi.")
        return
    # Check existing
    existing = sb_table_select("spare_parts", "*", filters=[("kode_barang", "eq", kode)])
    payload = {
        "kode_barang": kode,
        "nama_barang": nama,
        "spesifikasi": spesifikasi or "",
        "satuan": satuan or "pcs",
        "available_stock": float(stok or 0),
        "minimum_stock": float(min_stok or 0)
    }
    if not existing.empty:
        ok, res = sb_table_update("spare_parts", payload, "kode_barang", kode)
        if ok:
            st.success(f"✅ Data {kode} berhasil diperbarui.")
        else:
            st.error(f"Gagal update: {res}")
    else:
        ok, res = sb_table_insert("spare_parts", payload)
        if ok:
            st.success(f"✅ Data {kode} berhasil ditambahkan.")
        else:
            st.error(f"Gagal tambah: {res}")

def hapus_part(kode):
    if not kode:
        st.warning("Masukkan kode barang yang akan dihapus.")
        return
    ok, res = sb_table_delete("spare_parts", "kode_barang", kode)
    if ok:
        st.warning(f"🗑️ Data {kode} berhasil dihapus.")
    else:
        st.error(f"Gagal hapus: {res}")

def make_wo_no():
    today = datetime.now().strftime("%Y%m%d")
    # fetch count for the day from Supabase (fallback to 0)
    df = sb_table_select("work_orders", "id", filters=[("created_at", "like", f"{today}%")])
    seq = 1
    try:
        seq = (0 if df.empty else len(df)) + 1
    except Exception:
        seq = 1
    return f"WO-{today}-{seq:03d}"

def create_work_order(wo_type, asset_id, title, description, requester, assignee, priority, due_date, attachment_path=None):
    wo_no = make_wo_no()
    payload = {
        "wo_no": wo_no,
        "type": wo_type,
        "asset_id": asset_id,
        "title": title,
        "description": description,
        "requester": requester,
        "assignee": assignee,
        "status": "Open",
        "priority": priority,
        "created_at": datetime.now().isoformat(),
        "due_date": due_date.isoformat() if isinstance(due_date, date) else due_date,
        "attachment_path": attachment_path,
        "downtime_hours": 0,
        "cost": 0.0
    }
    ok, res = sb_table_insert("work_orders", payload)
    if ok:
        st.success(f"Work Order {wo_no} dibuat.")
        # backup
        df_wo = sb_table_select("work_orders", "*")
        if not df_wo.empty:
            save_backup_csv(df_wo, f"work_orders_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    else:
        st.error(f"Gagal membuat WO: {res}")

def add_activity_log(asset_id, act_date, act_type, location, description, technician, start_dt, end_dt, notes, attachment_path=None):
    duration_hours = 0.0
    try:
        duration_hours = round((end_dt - start_dt).total_seconds() / 3600, 2)
    except Exception:
        duration_hours = 0.0
    payload = {
        "asset_id": asset_id,
        "date": act_date.isoformat() if isinstance(act_date, date) else str(act_date),
        "type": act_type,
        "location": location,
        "description": description,
        "technician": technician,
        "start_time": start_dt.isoformat() if isinstance(start_dt, datetime) else str(start_dt),
        "end_time": end_dt.isoformat() if isinstance(end_dt, datetime) else str(end_dt),
        "duration_hours": duration_hours,
        "notes": notes,
        "attachment_path": attachment_path
    }
    ok, res = sb_table_insert("activity_log", payload)
    if ok:
        st.success(f"Activity '{act_type}' pada {payload['date']} tersimpan. Durasi: {duration_hours} jam.")
        # backup
        df_act = sb_table_select("activity_log", "*")
        if not df_act.empty:
            save_backup_csv(df_act, f"activity_log_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    else:
        st.error(f"Gagal menyimpan activity: {res}")

# =========================
# PAGES
# =========================
def page_dashboard():
    st.title("🛠️ BINTORO ENERGI PERSADA CMMS")
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=140)
    st.markdown("#### Sistem Manajemen Perawatan (CMMS) — Mode: Supabase (no-login)")

    # quick stats
    df_sp = load_spare_parts()
    df_wo = sb_table_select("work_orders", "*")
    df_act = sb_table_select("activity_log", "*")

    col1, col2, col3, col4 = st.columns(4)
    open_wo = int(df_wo[df_wo.get("status", "") != "Closed"].shape[0]) if not df_wo.empty else 0
    low_stock = int(df_sp[df_sp["available_stock"].astype(float) < df_sp["minimum_stock"].astype(float)].shape[0]) if not df_sp.empty else 0
    total_assets = "—"  # optional: implement assets table later
    total_parts = df_sp.shape[0] if not df_sp.empty else 0

    col1.metric("Open WO", open_wo)
    col2.metric("Low Stock", low_stock)
    col3.metric("Total Parts", total_parts)
    col4.metric("Activity Logs", df_act.shape[0] if not df_act.empty else 0)

    st.subheader("📋 Work Orders Terakhir")
    if not df_wo.empty:
        df_show = df_wo.sort_values("created_at", ascending=False).head(10)[["wo_no","type","title","status","priority","created_at","due_date"]]
        st.dataframe(df_show, use_container_width=True)
    else:
        st.info("Belum ada Work Orders.")

def page_spare_parts():
    st.title("📦 Inventory & Spare Parts (Supabase)")
    with st.expander("➕ Tambah / Update Spare Part"):
        with st.form("part_form", clear_on_submit=True):
            kode = st.text_input("Kode Barang")
            nama = st.text_input("Nama Barang")
            spesifikasi = st.text_area("Spesifikasi")
            satuan = st.text_input("Satuan (pcs, set, liter)", value="pcs")
            stok = st.number_input("Available Stock", min_value=0.0, value=0.0)
            min_stok = st.number_input("Minimum Stock", min_value=0.0, value=0.0)
            submitted = st.form_submit_button("Simpan")
        if submitted:
            tambah_atau_update_part(kode.strip(), nama.strip(), spesifikasi.strip(), satuan.strip(), stok, min_stok)

    st.markdown("---")
    df = load_spare_parts()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        # backup button
        if st.button("⬇️ Backup CSV Spare Parts"):
            path = save_backup_csv(df, f"spare_parts_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            st.success(f"Backup disimpan: {path}")
        to_excel_download_button(df, filename="spare_parts.xlsx", label="📘 Unduh Excel Spare Parts")
    else:
        st.info("Tidak ada data spare parts.")

    st.markdown("---")
    st.subheader("📥 Penerimaan (IN) & Pengeluaran (OUT)")
    parts = df
    if not parts.empty:
        with st.form("stock_txn_form", clear_on_submit=True):
            sel = st.selectbox("Pilih Part", parts["kode_barang"].astype(str) + " - " + parts["nama_barang"].astype(str))
            qty = st.number_input("Qty", min_value=0.0, value=1.0)
            txn_type = st.selectbox("Tipe Transaksi", ["IN", "OUT"])
            notes = st.text_input("Catatan", value="Manual adjustment")
            submit_tx = st.form_submit_button("Proses Transaksi")
        if submit_tx:
            kode_selected = sel.split(" - ")[0]
            # fetch part id / record
            rec = sb_table_select("spare_parts", "*", filters=[("kode_barang","eq",kode_selected)])
            if rec.empty:
                st.error("Part tidak ditemukan.")
            else:
                # update stok
                current = float(rec.iloc[0].get("available_stock", 0) or 0)
                if txn_type == "IN":
                    new = current + float(qty)
                else:
                    new = current - float(qty)
                    if new < 0:
                        new = 0
                ok, res = sb_table_update("spare_parts", {"available_stock": new}, "kode_barang", kode_selected)
                if ok:
                    # insert to stock_txn table (if exists)
                    tx_payload = {
                        "part_kode": kode_selected,
                        "txn_type": txn_type,
                        "qty": float(qty),
                        "notes": notes,
                        "created_at": datetime.now().isoformat()
                    }
                    sb_table_insert("stock_txn", tx_payload)
                    st.success("Transaksi stok berhasil diproses.")
                    # refresh backup
                    df_new = load_spare_parts()
                    save_backup_csv(df_new, f"spare_parts_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
                else:
                    st.error(f"Gagal update stok: {res}")
    else:
        st.info("Tidak ada part untuk transaksi.")

def page_workorders():
    st.title("🧾 Work Orders (CM & PM)")
    with st.expander("➕ Buat Work Order"):
        with st.form("form_wo_new", clear_on_submit=True):
            wo_type = st.selectbox("Tipe WO", ["CM", "PM"])
            # asset_id optional
            asset_id = st.text_input("Asset ID (opsional)")
            title = st.text_input("Judul WO")
            desc = st.text_area("Deskripsi WO")
            requester = st.text_input("Requester")
            assignee = st.text_input("Assigned To")
            priority = st.selectbox("Prioritas", ["Low", "Medium", "High", "Critical"], index=1)
            due = st.date_input("Due Date", value=date.today())
            submitted = st.form_submit_button("Buat WO")
        if submitted:
            create_work_order(wo_type, asset_id or None, title, desc, requester, assignee, priority, due)

    st.markdown("---")
    df = sb_table_select("work_orders", "*")
    if not df.empty:
        st.dataframe(df.sort_values("created_at", ascending=False), use_container_width=True)
    else:
        st.info("Belum ada Work Orders.")

    st.markdown("---")
    st.subheader("✏️ Update Work Order")
    if not df.empty:
        pick = st.selectbox("Pilih WO", df.apply(lambda r: f"{r.get('id','') } - {r.get('wo_no','') } - {r.get('status','')}", axis=1))
        if pick:
            try:
                wo_id = int(str(pick).split(" - ")[0])
            except Exception:
                wo_id = None
            if wo_id:
                wo_rec = df[df["id"] == wo_id].iloc[0].to_dict()
                c1, c2 = st.columns(2)
                with c1:
                    new_status = st.selectbox("Status", ["Open","In Progress","On Hold","Closed","Cancelled"], index=["Open","In Progress","On Hold","Closed","Cancelled"].index(wo_rec.get("status","Open")))
                    assignee = st.text_input("Assignee", value=wo_rec.get("assignee","") or "")
                    priority = st.selectbox("Prioritas", ["Low","Medium","High","Critical"], index=["Low","Medium","High","Critical"].index(wo_rec.get("priority","Medium")))
                    s_date = st.date_input("Start Date", value=date.today(), key="wo_sdate")
                    s_time = st.time_input("Start Time", value=dtime(hour=8, minute=0), key="wo_stime")
                    e_date = st.date_input("End Date", value=date.today(), key="wo_edate")
                    e_time = st.time_input("End Time", value=dtime(hour=9, minute=0), key="wo_etime")
                    cost = st.number_input("Biaya (IDR)", min_value=0.0, value=float(wo_rec.get("cost") or 0.0))
                    if st.button("💾 Simpan Perubahan WO"):
                        start_dt = datetime.combine(s_date, s_time)
                        end_dt = datetime.combine(e_date, e_time)
                        downtime = round((end_dt - start_dt).total_seconds() / 3600, 2) if end_dt >= start_dt else 0.0
                        ok, res = sb_table_update("work_orders", {
                            "status": new_status,
                            "assignee": assignee,
                            "priority": priority,
                            "start_time": start_dt.isoformat(),
                            "end_time": end_dt.isoformat(),
                            "downtime_hours": downtime,
                            "cost": float(cost)
                        }, "id", wo_id)
                        if ok:
                            st.success("WO berhasil diupdate.")
                        else:
                            st.error(f"Gagal update WO: {res}")
                with c2:
                    st.markdown("**Spare Parts yang Digunakan (manual)**")
                    sp_df = load_spare_parts()
                    if not sp_df.empty:
                        part_choices = sp_df["kode_barang"].astype(str) + " - " + sp_df["nama_barang"].astype(str)
                        chosen = st.selectbox("Pilih Part", part_choices)
                        qty = st.number_input("Qty Pemakaian", min_value=0.0, value=1.0, step=1.0)
                        if st.button("Tambah Part ke WO"):
                            kode_selected = chosen.split(" - ")[0]
                            # reduce stock
                            rec = sp_df[sp_df["kode_barang"] == kode_selected]
                            if rec.empty:
                                st.error("Part tidak ditemukan.")
                            else:
                                current = float(rec.iloc[0].get("available_stock", 0) or 0)
                                new = max(0, current - float(qty))
                                ok, res = sb_table_update("spare_parts", {"available_stock": new}, "kode_barang", kode_selected)
                                if ok:
                                    sb_table_insert("wo_parts", {"wo_id": wo_id, "part_kode": kode_selected, "qty": float(qty)})
                                    sb_table_insert("stock_txn", {"part_kode": kode_selected, "txn_type": "OUT", "qty": float(qty), "wo_id": wo_id, "notes": "use in WO", "created_at": datetime.now().isoformat()})
                                    st.success("Part ditambahkan ke WO dan stok dikurangi.")
                                else:
                                    st.error(f"Gagal mengurangi stok: {res}")
                    else:
                        st.info("Belum ada spare parts untuk dipilih.")
    else:
        st.info("Tidak ada WO untuk diupdate.")

def page_activity():
    st.title("📝 Activity Report — Breakdown & Shutdown")
    with st.expander("➕ Tambah Activity Report"):
        with st.form("form_add_activity", clear_on_submit=True):
            act_date = st.date_input("Tanggal Aktivitas", value=date.today())
            act_type = st.selectbox("Jenis Aktivitas", ["Breakdown", "Shutdown", "Routine"])
            asset_choice = st.text_input("Asset (opsional)")
            location = st.text_input("Lokasi / Area (opsional)")
            description = st.text_area("Uraian Pekerjaan / Root Cause")
            technician = st.text_input("Teknisi / PIC")
            st.markdown("**Waktu Mulai & Selesai**")
            s_date = st.date_input("Start Date", value=act_date, key="act_sdate")
            s_time = st.time_input("Start Time", value=dtime(hour=8, minute=0), key="act_stime")
            e_date = st.date_input("End Date", value=act_date, key="act_edate")
            e_time = st.time_input("End Time", value=dtime(hour=9, minute=0), key="act_etime")
            notes = st.text_area("Catatan / Tindakan Lanjutan (opsional)")
            submitted = st.form_submit_button("Simpan Activity")
        if submitted:
            start_dt = datetime.combine(s_date, s_time)
            end_dt = datetime.combine(e_date, e_time)
            add_activity_log(asset_choice or None, act_date, act_type, location, description, technician, start_dt, end_dt, notes)

    st.markdown("---")
    st.subheader("📋 Daftar Activity Reports")
    f_start = st.date_input("Filter: Start Date", value=(date.today() - timedelta(days=30)))
    f_end = st.date_input("Filter: End Date", value=date.today())
    f_type = st.selectbox("Filter: Type", ["All", "Breakdown", "Shutdown", "Routine"])
    qdf = sb_table_select("activity_log", "*")
    if not qdf.empty:
        qdf["date_parsed"] = pd.to_datetime(qdf["date"], errors="coerce")
        filt = (qdf["date_parsed"].dt.date >= f_start) & (qdf["date_parsed"].dt.date <= f_end)
        if f_type != "All":
            filt = filt & (qdf["type"] == f_type)
        out = qdf[filt].sort_values("date_parsed", ascending=False)
        if out.empty:
            st.info("Tidak ada activity pada rentang tanggal yang dipilih.")
        else:
            st.dataframe(out[["id","date","type","technician","duration_hours","notes"]], use_container_width=True)
            csv = out.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Unduh CSV (Filtered)", csv, "activity_reports_filtered.csv", "text/csv")
            if st.button("📄 Buat PDF Activity Report (Filtered)"):
                href = generate_pdf_report(f"Activity Report {f_start} to {f_end}", out[["date","type","technician","duration_hours","description"]], file_name=f"activity_{f_start}_{f_end}.pdf")
                st.markdown(href, unsafe_allow_html=True)
    else:
        st.info("Belum ada data activity.")

# =========================
# MAIN
# =========================
PAGES = {
    "Dashboard": page_dashboard,
    "Spare Parts": page_spare_parts,
    "Work Orders": page_workorders,
    "Activity Reports": page_activity,
}

st.sidebar.title("📁 Navigasi")
menu = st.sidebar.radio("", list(PAGES.keys()))
if supabase is None:
    st.sidebar.error("⚠️ Supabase client tidak dikonfigurasi. Buat file supabase_config.py atau set SUPABASE_URL & SUPABASE_KEY env vars.")
st.sidebar.markdown("---")
st.sidebar.markdown("⚙️ Mode: No-login (public access)  \n📂 Backup CSV: `data/`")

# run selected page
PAGES.get(menu, page_dashboard)()

# end of file
