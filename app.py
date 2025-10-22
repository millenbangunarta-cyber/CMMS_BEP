# app.py
# ==============================================================
#  BINTORO ENERGI PERSADA CMMS v3 (Cloud-ready)
#  Developer: ChatGPT (GPT-5 Thinking mini)
#  Date: 2025-10-19 (adapted)
# ==============================================================
# app_cmms_supabase.py
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date, time as dtime
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import matplotlib.pyplot as plt

# ==============================================================
# CONFIG
# ==============================================================
st.set_page_config(page_title="BINTORO ENERGI PERSADA CMMS",
                   page_icon="🛠️", layout="wide")

ROOT_DIR = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
DB_PATH = os.path.join(ROOT_DIR, "cmms.db")
UPLOAD_DIR = os.path.join(ROOT_DIR, "uploads")
LOGO_PATH = os.path.join(UPLOAD_DIR, "logo_bep.jpg")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DATA_DIR = os.path.join(ROOT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ==============================================================
# DATABASE
# ==============================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # assets
    cur.execute("""
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT NOT NULL,
        location TEXT,
        category TEXT,
        criticality TEXT,
        commissioning_date TEXT,
        photo_path TEXT,
        notes TEXT
    );
    """)

    # pm_plans
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pm_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
        task TEXT NOT NULL,
        frequency_days INTEGER NOT NULL,
        next_due_date TEXT NOT NULL,
        last_done_date TEXT
    );
    """)

    # work_orders
    cur.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wo_no TEXT UNIQUE,
        type TEXT CHECK(type IN ('PM','CM')) NOT NULL,
        asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        description TEXT,
        requester TEXT,
        assignee TEXT,
        status TEXT CHECK(status IN ('Open','In Progress','On Hold','Closed','Cancelled')) NOT NULL DEFAULT 'Open',
        priority TEXT CHECK(priority IN ('Low','Medium','High','Critical')) DEFAULT 'Medium',
        created_at TEXT NOT NULL,
        due_date TEXT,
        start_time TEXT,
        end_time TEXT,
        downtime_hours REAL DEFAULT 0,
        attachment_path TEXT,
        cost REAL DEFAULT 0,
        pm_plan_id INTEGER REFERENCES pm_plans(id) ON DELETE SET NULL
    );
    """)

    # spare_parts
    cur.execute("""
    CREATE TABLE IF NOT EXISTS spare_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kode_barang TEXT UNIQUE,
        nama_barang TEXT NOT NULL,
        spesifikasi TEXT,
        available_stock REAL DEFAULT 0,
        minimum_stock REAL DEFAULT 0,
        satuan TEXT DEFAULT 'pcs'
    );
    """)

    # wo_parts (parts used in a work order)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wo_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wo_id INTEGER REFERENCES work_orders(id) ON DELETE CASCADE,
        part_id INTEGER REFERENCES spare_parts(id) ON DELETE SET NULL,
        qty REAL NOT NULL
    );
    """)

    # stock transaksi
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_txn (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_id INTEGER REFERENCES spare_parts(id) ON DELETE CASCADE,
        txn_type TEXT CHECK(txn_type IN ('IN','OUT')) NOT NULL,
        qty REAL NOT NULL,
        wo_id INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
        notes TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # supplier
    cur.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        contact TEXT,
        phone TEXT,
        email TEXT,
        address TEXT,
        notes TEXT
    );
    """)

    # part_suppliers
    cur.execute("""
    CREATE TABLE IF NOT EXISTS part_suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part_id INTEGER REFERENCES spare_parts(id) ON DELETE CASCADE,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE CASCADE
    );
    """)

    # activity_reports
    cur.execute("""
    CREATE TABLE IF NOT EXISTS activity_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
        date TEXT NOT NULL,
        type TEXT CHECK(type IN ('Breakdown','Shutdown','Routine')) NOT NULL,
        location TEXT,
        description TEXT,
        technician TEXT,
        start_time TEXT,
        end_time TEXT,
        duration_hours REAL,
        notes TEXT,
        attachment_path TEXT
    );
    """)

    conn.commit()
    conn.close()

# ==============================================================
# HELPERS
# ==============================================================
def run_query(query, params=(), fetch=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    if fetch:
        data = cur.fetchall()
        conn.close()
        return data
    conn.close()

def fetch_df(query, params=()):
    conn = get_conn()
    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df

def make_wo_no():
    today = datetime.now().strftime("%Y%m%d")
    existing = fetch_df("SELECT COUNT(*) as c FROM work_orders WHERE created_at LIKE ?", (f"{today}%",))
    seq = int(existing.iloc[0]["c"]) + 1
    return f"WO-{today}-{seq:03d}"

def save_upload(file, prefix):
    if not file:
        return None
    fname = f"{prefix}_{int(datetime.now().timestamp())}_{file.name.replace(' ','_')}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(file.getbuffer())
    return fpath

def read_email_config():
    config_path = os.path.join(ROOT_DIR, "email_config.txt")
    if not os.path.exists(config_path):
        return None
    data = {}
    with open(config_path, "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                data[k.strip()] = v.strip()
    if not all(k in data for k in ["sender_email","app_password","recipient_email"]):
        return None
    return data

# ==============================================================
# EMAIL (OPTIONAL)
# ==============================================================
def send_email_notification(subject, body):
    cfg = read_email_config()
    if not cfg:
        st.warning("⚠️ email_config.txt tidak ditemukan atau format salah.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender_email"]
        msg["To"] = cfg["recipient_email"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(cfg["sender_email"], cfg["app_password"])
            server.send_message(msg)
        st.success("📤 Email notifikasi berhasil dikirim!")
        return True
    except Exception as e:
        st.error(f"Gagal mengirim email: {e}")
        return False

# ==============================================================
# DOWNTIME UTILS
# ==============================================================
def calc_downtime(start_dt, end_dt):
    if not start_dt or not end_dt:
        return 0.0
    try:
        dur = (end_dt - start_dt).total_seconds() / 3600
        return round(dur, 2)
    except Exception:
        return 0.0

# ==============================================================
# PDF REPORT
# ==============================================================
def generate_pdf_report(title, df, file_name="report.pdf"):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    if os.path.exists(LOGO_PATH):
        c.drawImage(LOGO_PATH, 2 * cm, height - 3 * cm, width=3 * cm, preserveAspectRatio=True)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(6 * cm, height - 2.5 * cm, title)
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 3.5 * cm, datetime.now().strftime("Tanggal Cetak: %d-%m-%Y %H:%M"))
    x, y = 2 * cm, height - 4.5 * cm
    c.setFont("Helvetica", 9)
    for col in df.columns:
        c.drawString(x, y, str(col))
        x += 3.5 * cm
    y -= 0.5 * cm
    x = 2 * cm
    for _, row in df.iterrows():
        for val in row:
            c.drawString(x, y, str(val)[:25])
            x += 3.5 * cm
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

# ==============================================================
# EXCEL DOWNLOAD HELPER (uses openpyxl)
# ==============================================================
def to_excel_download_button(df, filename="data.xlsx", sheet_name="Sheet1", label="Download Excel"):
    from io import BytesIO
    import pandas as pd
    import base64
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    processed_data = output.getvalue()
    b64 = base64.b64encode(processed_data).decode()
    href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">{label}</a>'
    st.markdown(href, unsafe_allow_html=True)

# ==============================================================
# PAGES
# ==============================================================
def page_dashboard():
    st.title("🛠️ BINTORO ENERGI PERSADA CMMS")
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=160)
    st.markdown("#### Sistem Manajemen Perawatan (CMMS)")

    c1, c2, c3, c4 = st.columns(4)
    open_wo = int(fetch_df("SELECT COUNT(*) as c FROM work_orders WHERE status!='Closed' AND status!='Cancelled'")["c"].iloc[0])
    overdue_pm = int(fetch_df("""SELECT COUNT(*) as c FROM pm_plans WHERE date(next_due_date) <= date('now')""")["c"].iloc[0])
    low_stock = int(fetch_df("SELECT COUNT(*) as c FROM spare_parts WHERE available_stock < minimum_stock")["c"].iloc[0])
    total_assets = int(fetch_df("SELECT COUNT(*) as c FROM assets")["c"].iloc[0])

    c1.metric("Open WO", open_wo)
    c2.metric("PM Due / Overdue", overdue_pm)
    c3.metric("Low Stock", low_stock)
    c4.metric("Total Assets", total_assets)

    st.subheader("🧾 Work Order Terbaru")
    df = fetch_df("""SELECT wo_no, type, title, status, priority, created_at, due_date
                     FROM work_orders ORDER BY id DESC LIMIT 10""")
    if not df.empty:
        st.dataframe(df, use_container_width=True)
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
        st.info("Belum ada data WO.")

    st.subheader("📤 Kirim Notifikasi Email")
    if st.button("Kirim Notifikasi WO & PM Due"):
        due_pm = fetch_df("""SELECT a.name as asset, p.task, p.next_due_date 
                             FROM pm_plans p LEFT JOIN assets a ON a.id=p.asset_id 
                             WHERE date(p.next_due_date) <= date('now')""")
        wo_open = fetch_df("""SELECT wo_no, title, due_date FROM work_orders 
                              WHERE status!='Closed' AND status!='Cancelled'""")
        body = "<h3>Reminder CMMS</h3>"
        body += "<p><b>PM Due:</b></p>" + due_pm.to_html(index=False) if not due_pm.empty else "<p>Tidak ada PM due.</p>"
        body += "<p><b>WO Open:</b></p>" + wo_open.to_html(index=False) if not wo_open.empty else "<p>Tidak ada WO open.</p>"
        send_email_notification("Reminder PM & WO Due - BEP CMMS", body)

def page_activity():
    st.title("📝 Activity Report — Breakdown & Shutdown")
    st.markdown("Catat aktivitas Breakdown atau Shutdown. Durasi dihitung otomatis dari start/end time.")
    assets = fetch_df("SELECT id, name FROM assets ORDER BY name ASC")
    asset_map = dict(zip(assets["name"], assets["id"])) if not assets.empty else {}

    with st.expander("➕ Tambah Activity Report"):
        with st.form("form_add_activity", clear_on_submit=True):
            act_date = st.date_input("Tanggal Aktivitas", value=date.today())
            act_type = st.selectbox("Jenis Aktivitas", ["Breakdown", "Shutdown", "Routine"])
            asset_choice = st.selectbox("Asset (opsional)", options=(["-"] + assets["name"].tolist())) if not assets.empty else st.text_input("Asset (ketik manual)")
            location = st.text_input("Lokasi / Area (opsional)")
            description = st.text_area("Uraian Pekerjaan / Root Cause")
            technician = st.text_input("Teknisi / PIC")
            st.markdown("**Waktu Mulai & Selesai**")
            s_date = st.date_input("Start Date", value=act_date, key="act_sdate")
            s_time = st.time_input("Start Time", value=dtime(hour=8, minute=0), key="act_stime")
            e_date = st.date_input("End Date", value=act_date, key="act_edate")
            e_time = st.time_input("End Time", value=dtime(hour=9, minute=0), key="act_etime")
            attachment = st.file_uploader("Lampiran (foto / dokumen) — opsional", type=["png","jpg","jpeg","pdf"])
            notes = st.text_area("Catatan / Tindakan Lanjutan (opsional)")
            submitted = st.form_submit_button("Simpan Activity")
        if submitted:
            asset_id = None
            if isinstance(asset_choice, str) and asset_choice != "-" and asset_choice.strip():
                asset_id = asset_map.get(asset_choice) if asset_choice in asset_map else None
            start_dt = datetime.combine(s_date, s_time)
            end_dt = datetime.combine(e_date, e_time)
            duration = calc_downtime(start_dt, end_dt)
            attach_path = save_upload(attachment, "activity") if attachment else None
            run_query(
                """INSERT INTO activity_reports(date, type, asset_id, description, technician,
                   start_time, end_time, duration_hours, notes, attachment_path)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (act_date.isoformat(), act_type, asset_id, description, technician,
                 start_dt.isoformat(), end_dt.isoformat(), duration, notes, attach_path)
            )
            st.success(f"Activity '{act_type}' pada {act_date.isoformat()} tersimpan. Durasi: {duration} jam.")

    st.markdown("---")
    st.subheader("📋 Daftar Activity Reports")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        f_start = st.date_input("Filter: Start Date", value=(date.today() - timedelta(days=30)))
    with col_f2:
        f_end = st.date_input("Filter: End Date", value=date.today())
    with col_f3:
        f_type = st.selectbox("Filter: Type", ["All", "Breakdown", "Shutdown", "Routine"])
    q = """SELECT ar.id, ar.date, ar.type, a.name AS asset, ar.location, ar.description,
                  ar.technician, ar.start_time, ar.end_time, ar.duration_hours, ar.notes, ar.attachment_path
           FROM activity_reports ar LEFT JOIN assets a ON a.id = ar.asset_id
           WHERE date(ar.date) BETWEEN date(?) AND date(?)"""
    params = [f_start.isoformat(), f_end.isoformat()]
    if f_type != "All":
        q += " AND ar.type = ?"
        params.append(f_type)
    q += " ORDER BY date(ar.date) DESC, ar.id DESC"
    act_df = fetch_df(q, tuple(params))
    if act_df.empty:
        st.info("Tidak ada activity pada rentang tanggal yang dipilih.")
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
        st.dataframe(act_df[["id","date","type","asset","technician","duration_hours","notes"]], use_container_width=True)
        csv = act_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Unduh CSV (Filtered)", csv, "activity_reports_filtered.csv", "text/csv")
        if st.button("📄 Buat PDF Activity Report (Filtered)"):
            title = f"Activity Report {f_type if f_type!='All' else 'All Types'} {f_start.isoformat()} to {f_end.isoformat()}"
            href = generate_pdf_report(title, act_df[["date","type","asset","technician","duration_hours","description"]], file_name=f"activity_{f_start}_{f_end}.pdf")
            st.markdown(href, unsafe_allow_html=True)
            st.success("PDF siap diunduh (klik link di atas).")

    st.markdown("---")
    st.subheader("🔎 Preview Lampiran Activity")
    sel_id = st.number_input("Masukkan ID Activity (kolom 'id') untuk preview lampiran", min_value=0, value=0, step=1)
    if sel_id:
        r = fetch_df("SELECT attachment_path FROM activity_reports WHERE id=?", (sel_id,))
        if not r.empty and r.iloc[0]["attachment_path"]:
            ap = r.iloc[0]["attachment_path"]
            if os.path.exists(ap):
                st.write(f"File: {os.path.basename(ap)}")
                if ap.lower().endswith((".png",".jpg",".jpeg")):
                    st.image(ap, use_column_width=True)
                else:
                    with open(ap, "rb") as f:
                        st.download_button("⬇️ Download Attachment", f.read(), os.path.basename(ap))
            else:
                st.error("File lampiran tidak ditemukan di server.")
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
            st.info("Tidak ada lampiran untuk ID tersebut atau ID tidak ditemukan.")

def page_workorders():
    st.title("🧾 Work Orders (WO) — CM & PM")
    assets = fetch_df("SELECT id, name FROM assets ORDER BY name ASC")
    parts = fetch_df("SELECT id, nama_barang, available_stock FROM spare_parts ORDER BY nama_barang ASC")
    asset_map = dict(zip(assets["name"], assets["id"])) if not assets.empty else {}
    part_map = dict(zip(parts["nama_barang"], parts["id"])) if not parts.empty else {}

    with st.expander("➕ Buat Work Order"):
        with st.form("form_wo_new", clear_on_submit=True):
            wo_type = st.selectbox("Tipe WO", ["CM", "PM"])
            asset_name = st.selectbox("Asset", assets["name"].tolist()) if not assets.empty else None
            title = st.text_input("Judul WO")
            desc = st.text_area("Deskripsi WO")
            requester = st.text_input("Requester")
            assignee = st.text_input("Assigned To")
            priority = st.selectbox("Prioritas", ["Low", "Medium", "High", "Critical"], index=1)
            due = st.date_input("Due Date", value=date.today())
            attach = st.file_uploader("Lampiran (optional)", type=["png","jpg","jpeg","pdf"])
            submitted = st.form_submit_button("Buat WO")
        if submitted:
            wo_no = make_wo_no()
            aid = asset_map.get(asset_name)
            attach_path = save_upload(attach, "wo") if attach else None
            run_query("""INSERT INTO work_orders(wo_no,type,asset_id,title,description,requester,assignee,
                         status,priority,created_at,due_date,attachment_path)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (wo_no, wo_type, aid, title, desc, requester, assignee,
                       "Open", priority, datetime.now().isoformat(), due.isoformat(), attach_path))
            st.success(f"Work Order {wo_no} dibuat.")

    st.subheader("📋 Daftar Work Orders")
    status_filter = st.multiselect("Filter Status",
        ["Open","In Progress","On Hold","Closed","Cancelled"],
        default=["Open","In Progress","On Hold"])
    df = fetch_df("""SELECT wo.id, wo.wo_no, wo.type, a.name AS asset, wo.title,
                            wo.priority, wo.status, wo.due_date, wo.created_at
                     FROM work_orders wo LEFT JOIN assets a ON a.id = wo.asset_id
                     ORDER BY wo.id DESC""")
    if not df.empty:
        df = df[df["status"].isin(status_filter)]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Belum ada WO.")

    st.subheader("✏️ Update Work Order")
    all_wo = fetch_df("SELECT id, wo_no, status FROM work_orders ORDER BY id DESC")
    if not all_wo.empty:
        pick = st.selectbox("Pilih WO", all_wo.apply(lambda r: f"{r['id']} - {r['wo_no']}", axis=1))
        wo_id = int(pick.split(" - ")[0])
        details = fetch_df("SELECT * FROM work_orders WHERE id=?",(wo_id,)).iloc[0].to_dict()
        st.write(details)
        c1, c2 = st.columns(2)
        with c1:
            new_status = st.selectbox("Status",
                ["Open","In Progress","On Hold","Closed","Cancelled"],
                index=["Open","In Progress","On Hold","Closed","Cancelled"].index(details["status"]))
            assignee = st.text_input("Assignee", value=details.get("assignee") or "")
            priority = st.selectbox("Prioritas",
                ["Low","Medium","High","Critical"],
                index=["Low","Medium","High","Critical"].index(details.get("priority") or "Medium"))
            st.markdown("**Waktu Mulai & Selesai**")
            s_date = st.date_input("Start Date", value=date.today(), key="wo_sdate")
            s_time = st.time_input("Start Time", value=datetime.now().time(), key="wo_stime")
            e_date = st.date_input("End Date", value=date.today(), key="wo_edate")
            e_time = st.time_input("End Time", value=datetime.now().time(), key="wo_etime")
            downtime = calc_downtime(datetime.combine(s_date, s_time), datetime.combine(e_date, e_time))
            cost = st.number_input("Biaya (IDR)", min_value=0.0, value=float(details.get("cost") or 0.0))
            if st.button("💾 Simpan Perubahan WO"):
                run_query("""UPDATE work_orders SET status=?, assignee=?, priority=?,
                             start_time=?, end_time=?, downtime_hours=?, cost=? WHERE id=?""",
                          (new_status, assignee, priority,
                           datetime.combine(s_date,s_time).isoformat(),
                           datetime.combine(e_date,e_time).isoformat(),
                           downtime, cost, wo_id))
                st.success(f"WO {details['wo_no']} diupdate. Downtime: {downtime} jam.")

        with c2:
            st.markdown("**⚙️ Spare Part yang Digunakan**")
            parts = fetch_df("SELECT id, nama_barang, available_stock FROM spare_parts ORDER BY nama_barang ASC")
            if parts.empty:
                st.info("Belum ada data part.")
            else:
                part_name = st.selectbox("Pilih Part", parts["nama_barang"].tolist(), key="wo_part")
                qty = st.number_input("Qty Pemakaian", min_value=0.0, value=1.0, key="wo_qty")
                if st.button("Tambah Part ke WO"):
                    pid = int(parts[parts["nama_barang"]==part_name]["id"].iloc[0])
                    # record in wo_parts
                    run_query("INSERT INTO wo_parts(wo_id, part_id, qty) VALUES(?,?,?)", (wo_id, pid, qty))
                    # decrease stock
                    run_query("UPDATE spare_parts SET available_stock = available_stock - ? WHERE id=?", (qty, pid))
                    run_query("""INSERT INTO stock_txn(part_id, txn_type, qty, wo_id, notes, created_at)
                                 VALUES(?, 'OUT', ?, ?, ?, ?)""",
                              (pid, qty, wo_id, "Use in WO", datetime.now().isoformat()))
                    st.success("Part ditambahkan dan stok berkurang.")
            st.warning("⚠️ Kode dan Nama Barang wajib diisi!")

            wop = fetch_df("""SELECT p.kode_barang, p.nama_barang, wp.qty FROM wo_parts wp
                              JOIN spare_parts p ON p.id = wp.part_id WHERE wp.wo_id=?""",(wo_id,))
            st.dataframe(wop, use_container_width=True)

def page_inventory():
    st.title("📦 Inventory & Spare Parts")
    with st.expander("➕ Tambah / Ubah Data Inventory"):
        with st.form("part_form", clear_on_submit=True):
            mode = st.selectbox("Mode", ["Tambah", "Update", "Hapus"])
            part_df = fetch_df("SELECT id, kode_barang, nama_barang FROM spare_parts ORDER BY id DESC")
            selected_id = None
            if mode != "Tambah" and not part_df.empty:
                selected = st.selectbox(
                    "Pilih Barang",
                    part_df.apply(lambda r: f"{r['id']} - {r['kode_barang']} - {r['nama_barang']}", axis=1)
                )
                selected_id = int(selected.split(" - ")[0])
            kode_barang = st.text_input("Kode Barang")
            nama_barang = st.text_input("Nama Barang")
            spesifikasi = st.text_area("Spesifikasi")
            available_stock = st.number_input("Available Stock", min_value=0.0, value=0.0)
            minimum_stock = st.number_input("Minimum Stock", min_value=0.0, value=0.0)
            satuan = st.text_input("Satuan (contoh: pcs, set, liter)", value="pcs")
            submitted = st.form_submit_button("Simpan")
        if submitted:
            if mode == "Tambah":
                run_query("""
                    INSERT INTO spare_parts(kode_barang, nama_barang, spesifikasi, available_stock, minimum_stock, satuan)
                    VALUES(?,?,?,?,?,?)
                """, (kode_barang, nama_barang, spesifikasi, available_stock, minimum_stock, satuan))
                st.success("Barang berhasil ditambahkan.")
            elif mode == "Update" and selected_id:
                run_query("""
                    UPDATE spare_parts
                    SET kode_barang=?, nama_barang=?, spesifikasi=?, available_stock=?, minimum_stock=?, satuan=?
                    WHERE id=?
                """, (kode_barang, nama_barang, spesifikasi, available_stock, minimum_stock, satuan, selected_id))
                st.success("Barang berhasil diperbarui.")
            elif mode == "Hapus" and selected_id:
                run_query("DELETE FROM spare_parts WHERE id=?", (selected_id,))
                st.success("Barang dihapus.")

    st.subheader("📤 Impor Data Inventory dari Excel")
    uploaded_file = st.file_uploader("Pilih file Excel (.xlsx)", type=["xlsx"])
    if uploaded_file:
        try:
            df_new = pd.read_excel(uploaded_file)
            df_new.rename(columns={
                "kode barang": "kode_barang",
                "nama barang": "nama_barang",
                "spesifikasi": "spesifikasi",
                "available stock": "available_stock",
                "minimum stock": "minimum_stock",
                "satuan": "satuan"
            }, inplace=True)
            st.dataframe(df_new, use_container_width=True)
            if st.button("📥 Impor ke Inventory"):
                conn = get_conn(); cur = conn.cursor()
                for _, r in df_new.iterrows():
                    cur.execute("""
                        INSERT OR REPLACE INTO spare_parts (kode_barang, nama_barang, spesifikasi, available_stock, minimum_stock, satuan)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        str(r.get("kode_barang", "")),
                        str(r.get("nama_barang", "")),
                        str(r.get("spesifikasi", "")),
                        float(r.get("available_stock", 0)),
                        float(r.get("minimum_stock", 0)),
                        str(r.get("satuan", "pcs"))
                    ))
                conn.commit(); conn.close()
                st.success("✅ Data inventory berhasil diimpor dari Excel!")
        except Exception as e:
            st.error(f"Gagal membaca file Excel: {e}")

    st.subheader("📋 Daftar Inventory")
    df = fetch_df("SELECT * FROM spare_parts ORDER BY nama_barang ASC")
    st.dataframe(df, use_container_width=True)
    to_excel_download_button(df, filename="inventory.xlsx", sheet_name="Inventory", label="📘 Unduh Excel Inventory")

    st.subheader("📥 Penerimaan (IN)")
    parts = fetch_df("SELECT id, nama_barang FROM spare_parts ORDER BY nama_barang ASC")
    if not parts.empty:
        with st.form("form_stock_in", clear_on_submit=True):
            pname = st.selectbox("Pilih Part", parts["nama_barang"].tolist())
            qty = st.number_input("Qty Masuk", min_value=0.0, value=1.0)
            notes = st.text_input("Catatan", value="Penerimaan")
            if st.form_submit_button("Tambah IN"):
                pid = dict(zip(parts["nama_barang"], parts["id"]))[pname]
                run_query("UPDATE spare_parts SET available_stock = available_stock + ? WHERE id=?", (qty, pid))
                run_query("""INSERT INTO stock_txn(part_id, txn_type, qty, notes, created_at)
                             VALUES(?, 'IN', ?, ?, ?)""", (pid, qty, notes, datetime.now().isoformat()))
                st.success("Transaksi IN tersimpan.")

    st.subheader("📋 Daftar Spare Parts")
    df = fetch_df("SELECT * FROM spare_parts ORDER BY nama_barang ASC")
    st.dataframe(df, use_container_width=True)
    st.download_button("⬇️ Unduh CSV Part", df.to_csv(index=False).encode("utf-8"), "spare_parts.csv", "text/csv")

    st.subheader("🧾 Riwayat Transaksi")
    tx = fetch_df("""SELECT t.id, p.nama_barang AS part, t.txn_type, t.qty, t.wo_id, t.notes, t.created_at
                     FROM stock_txn t JOIN spare_parts p ON p.id=t.part_id
                     ORDER BY t.id DESC LIMIT 200""")
    st.dataframe(tx, use_container_width=True)
    st.download_button("⬇️ Unduh CSV Transaksi", tx.to_csv(index=False).encode("utf-8"), "stock_txn.csv", "text/csv")

def page_suppliers():
    st.title("🏷️ Suppliers")
    with st.expander("➕ Tambah / Ubah Supplier"):
        with st.form("form_sup", clear_on_submit=True):
            mode = st.selectbox("Mode", ["Tambah","Update","Hapus"])
            df_sup = fetch_df("SELECT id,name FROM suppliers ORDER BY name ASC")
            sid = None
            if mode != "Tambah" and not df_sup.empty:
                pick = st.selectbox("Pilih Supplier", df_sup.apply(lambda r: f"{r['id']} - {r['name']}", axis=1))
                sid = int(pick.split(" - ")[0])
            name = st.text_input("Nama Supplier")
            contact = st.text_input("Kontak")
            phone = st.text_input("Telepon")
            email = st.text_input("Email")
            address = st.text_area("Alamat")
            notes = st.text_area("Catatan")
            submit = st.form_submit_button("Simpan")
        if submit:
            if mode == "Tambah":
                run_query("""INSERT INTO suppliers(name,contact,phone,email,address,notes)
                             VALUES(?,?,?,?,?,?)""", (name, contact, phone, email, address, notes))
                st.success("Supplier ditambahkan.")
            elif mode == "Update" and sid:
                run_query("""UPDATE suppliers SET name=?, contact=?, phone=?, email=?, address=?, notes=? WHERE id=?""",
                          (name, contact, phone, email, address, notes, sid))
                st.success("Supplier diupdate.")
            elif mode == "Hapus" and sid:
                run_query("DELETE FROM suppliers WHERE id=?", (sid,))
                st.success("Supplier dihapus.")
    st.subheader("📋 Daftar Supplier")
    df = fetch_df("SELECT * FROM suppliers ORDER BY name ASC")
    st.dataframe(df, use_container_width=True)

def page_reports():
    st.title("📊 Reports & Analytics")
    assets = fetch_df("SELECT id,name FROM assets ORDER BY name ASC")
    if assets.empty:
        st.info("Tambahkan asset terlebih dahulu untuk laporan.")
        return
    asset = st.selectbox("Pilih Asset", assets["name"].tolist())
    aid = dict(zip(assets["name"], assets["id"]))[asset]
    df_wo = fetch_df("""SELECT wo_no,type,status,priority,downtime_hours,cost FROM work_orders WHERE asset_id=?""",(aid,))
    total_cost = df_wo["cost"].sum() if not df_wo.empty else 0
    avg_downtime = df_wo["downtime_hours"].mean() if not df_wo.empty else 0
    st.metric("Total Cost (IDR)", f"{int(total_cost):,}")
    st.metric("Rata-rata Downtime (jam)", round(avg_downtime,2))
    st.dataframe(df_wo, use_container_width=True)

    st.subheader("📄 Laporan Activity Terbaru")
    df_act = fetch_df("""SELECT date,type,technician,duration_hours,description
                         FROM activity_reports ORDER BY date DESC LIMIT 10""")
    st.dataframe(df_act, use_container_width=True)

def page_settings():
    st.title("⚙️ Settings & Backup")
    tables = ["assets","pm_plans","work_orders","spare_parts","stock_txn","suppliers","activity_reports","wo_parts"]
    for t in tables:
        df = fetch_df(f"SELECT * FROM {t}")
        st.download_button(f"⬇️ Unduh {t}.csv", df.to_csv(index=False).encode("utf-8"), f"{t}.csv", "text/csv")
    st.markdown("---")
    st.write("Impor CSV ke tabel (opsional overwrite).")
    table = st.selectbox("Tabel tujuan", tables)
    f = st.file_uploader("Upload CSV")
    overwrite = st.checkbox("Hapus isi tabel sebelum impor?", value=False)
    if st.button("Impor CSV") and f:
        df = pd.read_csv(f)
        conn = get_conn()
        cur = conn.cursor()
        if overwrite:
            cur.execute(f"DELETE FROM {table}")
        cols = ",".join(df.columns)
        qmark = ",".join(["?"]*len(df.columns))
        cur.executemany(f"INSERT INTO {table} ({cols}) VALUES ({qmark})", df.values.tolist())
        conn.commit(); conn.close()
        st.success(f"Impor {table} selesai.")

# ==============================================================
# MAIN
# ==============================================================
init_db()
menu = st.sidebar.selectbox("📁 Navigasi", [
    "Dashboard","Work Orders","Inventory","Suppliers","Activity Reports","Reports","Settings"
])
if menu == "Dashboard":
    page_dashboard()
elif menu == "Work Orders":
    page_workorders()
elif menu == "Inventory":
    page_inventory()
elif menu == "Suppliers":
    page_suppliers()
elif menu == "Activity Reports":
    page_activity()
elif menu == "Reports":
    page_reports()
elif menu == "Settings":
    page_settings()
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
