# app_cmms_supabase.py
# BINTORO ENERGI PERSADA — CMMS Cloud v3
# Streamlit + Supabase (no-login front-end)
# Date: 2025-10-22 (adapted)

import os
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time as dtime
from io import BytesIO
import base64

# -------------------------
# REQUIRE: supabase-py installed (package name: supabase-py)
# -------------------------
try:
    from supabase import create_client, Client
except Exception as e:
    st.error("Module 'supabase' tidak ditemukan. Pastikan requirements.txt berisi 'supabase-py'.")
    raise

# -------------------------
# Config: Secrets (Streamlit Cloud)
# -------------------------
# On Streamlit Cloud -> Settings -> Secrets:
# SUPABASE_URL = "https://xxxxx.supabase.co"
# SUPABASE_KEY = "ey...your_anon_key..."
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials missing. Tambahkan SUPABASE_URL & SUPABASE_KEY ke Streamlit Secrets.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# App config: data dir that is safe in Cloud vs Local
# -------------------------
if os.getenv("STREAMLIT_RUNTIME") == "true":
    DATA_DIR = "/tmp/cmms_data"
else:
    DATA_DIR = "data"

if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass  # silently continue; if cannot create, app still works (uses supabase)

# -------------------------
# Utility helpers: CSV/Excel/PDF
# -------------------------
def save_backup_csv(df: pd.DataFrame, name: str):
    fname = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path = os.path.join(DATA_DIR, fname)
    df.to_csv(path, index=False)
    return path

def to_excel_bytes(df: pd.DataFrame):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def excel_download_link(df: pd.DataFrame, filename="data.xlsx", label="Download Excel"):
    b = to_excel_bytes(df)
    b64 = base64.b64encode(b).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">{label}</a>'
    return href

def pdf_report_link(title, df: pd.DataFrame, filename="report.pdf"):
    # simple CSV-as-pdf fallback could be added; for brevity return CSV download link
    b = df.to_csv(index=False).encode("utf-8")
    b64 = base64.b64encode(b).decode()
    href = f'<a href="data:text/csv;base64,{b64}" download="{filename.replace(".pdf",".csv")}">Download CSV (as report)</a>'
    return href

# -------------------------
# Supabase wrapper helpers (safe)
# -------------------------
def sb_select(table, columns="*", filters=None, order=None, limit=None):
    try:
        q = supabase.table(table).select(columns)
        if filters:
            # filters: list of (col, op, val) with op like "eq","like"
            for col, op, val in filters:
                q = getattr(q, op)(col, val)
        if order:
            q = q.order(order[0], order[1])
        if limit:
            q = q.limit(limit)
        r = q.execute()
        data = r.data if hasattr(r, "data") else r
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"Supabase select error: {e}")
        return pd.DataFrame()

def sb_insert(table, payload):
    try:
        r = supabase.table(table).insert(payload).execute()
        return r
    except Exception as e:
        st.error(f"Supabase insert error: {e}")
        return None

def sb_upsert(table, payload):
    try:
        r = supabase.table(table).upsert(payload).execute()
        return r
    except Exception as e:
        st.error(f"Supabase upsert error: {e}")
        return None

def sb_update(table, payload, match_col, match_val):
    try:
        r = supabase.table(table).update(payload).eq(match_col, match_val).execute()
        return r
    except Exception as e:
        st.error(f"Supabase update error: {e}")
        return None

def sb_delete(table, match_col, match_val):
    try:
        r = supabase.table(table).delete().eq(match_col, match_val).execute()
        return r
    except Exception as e:
        st.error(f"Supabase delete error: {e}")
        return None

# -------------------------
# Domain functions: Inventory, Assets, Work Orders, PM, Activity
# -------------------------
# Inventory
def load_inventory():
    return sb_select("spare_parts", "*", order=("nama_barang","asc"))

def add_or_update_part(kode, nama, spesifikasi, satuan, available_stock, minimum_stock):
    if not kode or not nama:
        st.warning("Kode & Nama wajib diisi")
        return
    existing = sb_select("spare_parts", "*", filters=[("kode_barang","eq",kode)])
    payload = {
        "kode_barang": kode,
        "nama_barang": nama,
        "spesifikasi": spesifikasi or "",
        "satuan": satuan or "pcs",
        "available_stock": float(available_stock or 0),
        "minimum_stock": float(minimum_stock or 0)
    }
    if not existing.empty:
        sb_update("spare_parts", payload, "kode_barang", kode)
        st.success(f"Part {kode} diperbarui.")
    else:
        sb_insert("spare_parts", payload)
        st.success(f"Part {kode} ditambahkan.")
    # backup
    df = load_inventory()
    if not df.empty:
        save_backup_csv(df, "spare_parts_backup")

# Assets (equipment)
def load_assets():
    return sb_select("assets", "*", order=("name","asc"))

def add_asset(code, name, location, category, criticality, commissioning_date, notes):
    payload = {
        "code": code,
        "name": name,
        "location": location,
        "category": category,
        "criticality": criticality,
        "commissioning_date": commissioning_date,
        "notes": notes
    }
    sb_insert("assets", payload)
    st.success("Asset ditambahkan.")

# Work Orders
def make_wo_no():
    today = datetime.now().strftime("%Y%m%d")
    df = sb_select("work_orders", "id", filters=[("created_at","like",f"{today}%")])
    seq = 1 if df.empty else len(df) + 1
    return f"WO-{today}-{seq:03d}"

def create_work_order(wo_type, asset_id, title, description, requester, assignee, priority, due_date):
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
        "downtime_hours": 0,
        "cost": 0.0
    }
    sb_insert("work_orders", payload)
    st.success(f"Work Order {wo_no} dibuat.")
    # backup
    df = sb_select("work_orders","*")
    if not df.empty:
        save_backup_csv(df, "work_orders_backup")

# Preventive Maintenance (PM)
def load_pm_plans():
    return sb_select("pm_plans", "*", order=("next_due_date","asc"))

def add_pm_plan(asset_id, task, frequency_days, next_due_date):
    payload = {
        "asset_id": asset_id,
        "task": task,
        "frequency_days": int(frequency_days),
        "next_due_date": next_due_date.isoformat() if isinstance(next_due_date, date) else next_due_date
    }
    sb_insert("pm_plans", payload)
    st.success("PM Plan ditambahkan.")

# Activity logs
def add_activity(asset_id, date_, type_, location, description, technician, start_time, end_time, notes):
    dur = 0.0
    try:
        dur = round((end_time - start_time).total_seconds()/3600,2)
    except Exception:
        dur = 0.0
    payload = {
        "asset_id": asset_id,
        "date": date_.isoformat() if isinstance(date_, date) else str(date_),
        "type": type_,
        "location": location,
        "description": description,
        "technician": technician,
        "start_time": start_time.isoformat() if isinstance(start_time, datetime) else str(start_time),
        "end_time": end_time.isoformat() if isinstance(end_time, datetime) else str(end_time),
        "duration_hours": dur,
        "notes": notes
    }
    sb_insert("activity_log", payload)
    st.success("Activity tercatat.")
    # backup
    df = sb_select("activity_log","*")
    if not df.empty:
        save_backup_csv(df, "activity_log_backup")

# Reports helpers
def generate_basic_reports():
    # summarize WO by status, inventory low stock, PM due
    wo = sb_select("work_orders","status,downtime_hours,cost")
    spare = load_inventory()
    pm = load_pm_plans()
    stats = {}
    stats["total_wo"] = 0 if wo.empty else len(wo)
    stats["open_wo"] = 0 if wo.empty else (wo["status"]=="Open").sum()
    stats["total_parts"] = 0 if spare.empty else len(spare)
    stats["low_stock_count"] = 0 if spare.empty else (spare["available_stock"].astype(float) < spare["minimum_stock"].astype(float)).sum()
    stats["pm_due"] = 0 if pm.empty else (pd.to_datetime(pm["next_due_date"], errors="coerce").dt.date <= date.today()).sum()
    return stats

# -------------------------
# Streamlit UI — dark theme already controlled by .streamlit/config.toml
# -------------------------
st.set_page_config(page_title="BEP CMMS Cloud", page_icon="🛠️", layout="wide")

st.sidebar.title("📁 Navigasi")
menu = st.sidebar.radio("", ["Dashboard","Work Orders","Preventive (PM)","Inventory","Assets","Activity","Reports","Settings"])

# DASHBOARD
if menu == "Dashboard":
    st.title("🛠️ Dashboard — BEP CMMS")
    stats = generate_basic_reports()
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Open WO", stats["open_wo"])
    c2.metric("PM Due / Overdue", stats["pm_due"])
    c3.metric("Low Stock", stats["low_stock_count"])
    c4.metric("Total Parts", stats["total_parts"])
    st.markdown("---")
    st.subheader("Work Orders Terbaru")
    df_wo = sb_select("work_orders","wo_no,type,title,status,priority,created_at,due_date", order=("created_at","desc"), limit=10)
    if not df_wo.empty:
        st.dataframe(df_wo, use_container_width=True)
    else:
        st.info("Belum ada Work Orders.")

# WORK ORDERS
elif menu == "Work Orders":
    st.title("🧾 Work Orders")
    with st.expander("➕ Buat Work Order"):
        with st.form("form_wo", clear_on_submit=True):
            wo_type = st.selectbox("Tipe", ["CM","PM"])
            assets_df = load_assets()
            asset_opts = ["-"] + (assets_df["id"].astype(str).tolist() if not assets_df.empty else [])
            asset_id = st.selectbox("Asset (ID)", asset_opts)
            title = st.text_input("Judul")
            desc = st.text_area("Deskripsi")
            requester = st.text_input("Requester")
            assignee = st.text_input("Assignee")
            priority = st.selectbox("Prioritas", ["Low","Medium","High","Critical"], index=1)
            due = st.date_input("Due Date", value=date.today())
            submit = st.form_submit_button("Buat WO")
        if submit:
            create_work_order(wo_type, None if asset_id == "-" else int(asset_id), title, desc, requester, assignee, priority, due)

    st.markdown("---")
    df = sb_select("work_orders","*", order=("created_at","desc"))
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Belum ada WO.")

# PM
elif menu == "Preventive (PM)":
    st.title("🗓️ Preventive Maintenance (PM)")
    with st.expander("➕ Tambah PM Plan"):
        with st.form("form_pm", clear_on_submit=True):
            assets_df = load_assets()
            asset_opts = ["-"] + (assets_df["id"].astype(str).tolist() if not assets_df.empty else [])
            asset_id = st.selectbox("Asset (ID)", asset_opts)
            task = st.text_input("Task")
            freq = st.number_input("Frequency (hari)", min_value=1, value=30)
            next_due = st.date_input("Next Due", value=date.today()+timedelta(days=freq))
            submit = st.form_submit_button("Simpan PM")
        if submit:
            add_pm_plan(None if asset_id == "-" else int(asset_id), task, freq, next_due)

    st.markdown("---")
    df = load_pm_plans()
    if df.empty:
        st.info("Belum ada PM.")
    else:
        st.dataframe(df, use_container_width=True)

# INVENTORY
elif menu == "Inventory":
    st.title("📦 Inventory & Spare Parts")
    with st.expander("➕ Tambah / Update Part"):
        with st.form("form_part", clear_on_submit=True):
            kode = st.text_input("Kode Barang")
            nama = st.text_input("Nama Barang")
            spes = st.text_area("Spesifikasi")
            satuan = st.text_input("Satuan", value="pcs")
            avail = st.number_input("Available Stock", min_value=0.0, value=0.0)
            mini = st.number_input("Minimum Stock", min_value=0.0, value=0.0)
            submit = st.form_submit_button("Simpan")
        if submit:
            add_or_update_part(kode.strip(), nama.strip(), spes.strip(), satuan.strip(), avail, mini)

    st.markdown("---")
    df = load_inventory()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        if st.button("⬇️ Backup CSV spare_parts"):
            path = save_backup_csv(df, "spare_parts_backup")
            st.success(f"Backup saved: {path}")
        st.markdown(excel_download_link(df, filename="spare_parts.xlsx", label="📘 Unduh Excel Spare Parts"), unsafe_allow_html=True)
    else:
        st.info("Belum ada data spare parts.")

# ASSETS
elif menu == "Assets":
    st.title("🏷️ Asset Register (Equipment)")
    with st.expander("➕ Tambah Asset"):
        with st.form("form_asset", clear_on_submit=True):
            code = st.text_input("Code")
            name = st.text_input("Name")
            location = st.text_input("Location")
            category = st.text_input("Category")
            criticality = st.selectbox("Criticality", ["Low","Medium","High","Critical"], index=1)
            comm = st.date_input("Commissioning Date", value=date.today())
            notes = st.text_area("Notes")
            submit = st.form_submit_button("Tambah Asset")
        if submit:
            add_asset(code, name, location, category, criticality, comm.isoformat(), notes)

    st.markdown("---")
    df = load_assets()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Belum ada asset.")

# ACTIVITY
elif menu == "Activity":
    st.title("📝 Activity Log")
    with st.expander("➕ Tambah Activity Report"):
        with st.form("form_act", clear_on_submit=True):
            act_date = st.date_input("Date", value=date.today())
            act_type = st.selectbox("Type", ["Breakdown","Shutdown","Routine"])
            asset_input = st.text_input("Asset ID (optional)")
            loc = st.text_input("Location")
            desc = st.text_area("Description")
            tech = st.text_input("Technician")
            s_date = st.date_input("Start Date", value=act_date, key="sdt")
            s_time = st.time_input("Start Time", value=dtime(8,0), key="stt")
            e_date = st.date_input("End Date", value=act_date, key="edt")
            e_time = st.time_input("End Time", value=dtime(9,0), key="ett")
            notes = st.text_area("Notes")
            submit = st.form_submit_button("Simpan Activity")
        if submit:
            st_dt = datetime.combine(s_date, s_time)
            en_dt = datetime.combine(e_date, e_time)
            add_activity(None if not asset_input else int(asset_input), act_date, act_type, loc, desc, tech, st_dt, en_dt, notes)

    st.markdown("---")
    df = sb_select("activity_log","*", order=("date","desc"))
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Belum ada activity.")

# REPORTS
elif menu == "Reports":
    st.title("📈 Reports")
    st.subheader("Ringkasan Utama")
    stats = generate_basic_reports()
    st.write(stats)
    st.markdown("---")
    if st.button("Export Semua Tables ke CSV (Backup)"):
        for t in ["spare_parts","work_orders","assets","pm_plans","activity_log","stock_txn","wo_parts"]:
            df = sb_select(t,"*")
            if not df.empty:
                p = save_backup_csv(df, t + "_backup")
                st.write(f"{t} -> {p}")
        st.success("Semua tabel dibackup ke folder data/")

# SETTINGS
elif menu == "Settings":
    st.title("⚙️ Settings & Info")
    st.info("Supabase URL read from Streamlit Secrets.")
    st.write("SUPABASE_URL (hidden) configured in Secrets.")
    st.markdown("**Deployment notes**: Push changes to GitHub -> Streamlit Cloud redeploys automatically.")
