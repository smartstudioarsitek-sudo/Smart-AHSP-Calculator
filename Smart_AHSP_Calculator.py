import streamlit as st
import pandas as pd
import csv
import io

st.set_page_config(page_title="Smart RAB System 2025", layout="wide", initial_sidebar_state="expanded")

# --- CSS STYLING ---
st.markdown("""
<style>
    .big-font {font-size:24px !important; font-weight: bold;}
    .metric-container {background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b;}
    div[data-testid="stExpander"] {border: 1px solid #e0e0e0; border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

# --- FUNGSI 1: LOAD DATABASE HARGA ---
@st.cache_data
def load_master_db(file_obj):
    try:
        # Deteksi Header (Cari baris yang ada kata KODE dan SATUAN)
        content = file_obj.getvalue().decode("utf-8", errors='ignore')
        header_row = -1
        lines = content.splitlines()
        for i, line in enumerate(lines[:30]):
            if "KODE" in line.upper() and "SATUAN" in line.upper():
                header_row = i
                break
        
        if header_row == -1: return pd.DataFrame()

        file_obj.seek(0)
        df = pd.read_csv(file_obj, header=header_row)
        
        # Mapping Kolom
        col_map = {}
        for c in df.columns:
            c_up = str(c).upper()
            if "KODE" in c_up: col_map['kode'] = c
            elif "URAIAN" in c_up or "UPAH" in c_up: col_map['uraian'] = c
            elif "SATUAN" in c_up and "HARGA" not in c_up: col_map['satuan'] = c
            elif "HARGA" in c_up: col_map['harga'] = c

        clean_data = []
        for _, row in df.iterrows():
            try:
                # Ambil data
                uraian = str(row[col_map.get('uraian')]).strip()
                if not uraian or uraian.lower() == 'nan': continue
                
                kode = str(row[col_map.get('kode', '')]).strip()
                satuan = str(row[col_map.get('satuan', '')]).strip()
                
                # Bersihkan Harga
                h_raw = str(row[col_map.get('harga', '0')]).replace('.', '').replace(',', '.')
                try: harga = float(h_raw)
                except: harga = 0
                
                clean_data.append({'Kode': kode, 'Uraian': uraian, 'Satuan': satuan, 'Harga': harga})
            except: continue
            
        return pd.DataFrame(clean_data)
    except: return pd.DataFrame()

# --- FUNGSI 2: PARSING ANALISA (MESIN UTAMA) ---
def parse_analysis_file(file_obj):
    job_items = {}
    content = file_obj.getvalue().decode("utf-8", errors='ignore')
    f = io.StringIO(content)
    reader = csv.reader(f)
    
    current_job = None
    components = []
    capture = False
    
    for parts in reader:
        if not parts: continue
        parts = [p.strip() for p in parts]
        
        # Deteksi Judul Pekerjaan (X.X.X.X)
        id_val, desc_val = None, None
        for i, p in enumerate(parts):
            if len(p) >= 3 and p[0].isdigit() and '.' in p and len(p) < 20:
                if i+1 < len(parts) and len(parts[i+1]) > 5:
                    id_val = p
                    desc_val = parts[i+1]
                    break
        
        if id_val and desc_val:
            if current_job: job_items[current_job] = components
            current_job = f"{id_val} - {desc_val}"
            components = []
            capture = True
            continue
            
        # Deteksi Komponen
        if capture and current_job:
            if any(x in "".join(parts).upper() for x in ["URAIAN", "JUMLAH", "HARGA SATUAN"]): continue
            
            # Cari Koefisien
            coeff_idx = -1
            for i, p in enumerate(parts):
                if not p: continue
                try:
                    val = float(p)
                    if 0 <= val < 10000 and i > 0 and 0 < len(parts[i-1]) <= 8:
                        coeff_idx = i
                        break
                except: pass
            
            if coeff_idx != -1:
                try:
                    components.append({
                        'uraian': parts[coeff_idx-2] if coeff_idx >= 2 and len(parts[coeff_idx-2]) > 2 else parts[coeff_idx-3],
                        'kode': parts[coeff_idx-2] if coeff_idx >= 2 and ('.' in parts[coeff_idx-2] or parts[coeff_idx-2].isalnum()) else "-",
                        'unit': parts[coeff_idx-1],
                        'koef': float(parts[coeff_idx])
                    })
                except: pass

    if current_job: job_items[current_job] = components
    return job_items

# --- FUNGSI 3: HITUNG HARGA SATUAN (HSP) ---
def hitung_hsp(components, price_db):
    total_basic = 0
    for c in components:
        # Lookup Harga
        h = 0
        if c['kode'] in price_db: h = price_db[c['kode']]
        elif c['uraian'].lower() in price_db: h = price_db[c['uraian'].lower()]
        else:
            # Partial match
            for k, v in price_db.items():
                if k in c['uraian'].lower(): 
                    h = v; break
        total_basic += (c['koef'] * h)
    
    overhead = total_basic * 0.10
    return total_basic + overhead

# ==========================================
#               USER INTERFACE
# ==========================================

st.title("🏗️ Sistem Manajemen RAB - SE PUPR 30/2025")
st.write("Fitur: Template Harga, Template Volume (BoQ), dan Perhitungan Batch.")

# --- TABS NAVIGASI ---
tab1, tab2, tab3 = st.tabs(["📂 1. Upload Data", "📝 2. Input Harga & Volume", "💰 3. Hasil RAB"])

# GLOBAL VARIABLES
if 'master_prices' not in st.session_state: st.session_state.master_prices = {}
if 'analisa_jobs' not in st.session_state: st.session_state.analisa_jobs = {}

# --- TAB 1: UPLOAD DATA ---
with tab1:
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.header("A. Data Harga (Upah/Bahan)")
        file_master = st.file_uploader("Upload 'Upah Bahan.csv'", type='csv')
        if file_master:
            df_master = load_master_db(file_master)
            if not df_master.empty:
                # Simpan ke session state sebagai default
                st.session_state.master_prices = {}
                for _, row in df_master.iterrows():
                    st.session_state.master_prices[str(row['Uraian']).lower()] = row['Harga']
                    if row['Kode'] != "-" and row['Kode'] != "nan":
                        st.session_state.master_prices[row['Kode']] = row['Harga']
                st.success(f"✅ {len(df_master)} Item Harga Terbaca")
    
    with col_b:
        st.header("B. Data Analisa (Pekerjaan)")
        files_analisa = st.file_uploader("Upload File Analisa (.csv)", type='csv', accept_multiple_files=True)
        if files_analisa:
            jobs = {}
            for f in files_analisa:
                jobs.update(parse_analysis_file(f))
            st.session_state.analisa_jobs = jobs
            st.success(f"✅ {len(jobs)} Analisa Pekerjaan Terbaca")

# --- TAB 2: INPUT & TEMPLATE ---
with tab2:
    if not st.session_state.master_prices or not st.session_state.analisa_jobs:
        st.warning("⚠️ Harap upload file di Tab 1 terlebih dahulu.")
    else:
        st.info("Di sini Anda bisa mendownload template untuk mengisi Harga Baru dan Volume Pekerjaan.")
        
        c1, c2 = st.columns(2)
        
        # --- KOLOM 1: TEMPLATE HARGA ---
        with c1:
            st.subheader("1. Template Harga")
            st.caption("Gunakan ini jika ingin mengubah harga dasar (Upah/Bahan).")
            
            # Generate Template Harga
            if file_master: # Re-use df_master if possible or re-load
                file_master.seek(0)
                df_m = load_master_db(file_master)
                df_temp_harga = df_m[['Kode', 'Uraian', 'Satuan', 'Harga']].copy()
                df_temp_harga.rename(columns={'Harga': 'Harga_Standar'}, inplace=True)
                df_temp_harga['Harga_Baru'] = 0 # Kolom input user
                
                st.download_button("⬇️ Download Template Harga", 
                                 df_temp_harga.to_csv(index=False).encode('utf-8'), 
                                 "Template_Harga.csv", "text/csv")
            
            # Upload Balik
            upload_harga = st.file_uploader("Upload Template Harga (Terisi)", type='csv')
            if upload_harga:
                df_new = pd.read_csv(upload_harga)
                count = 0
                for _, row in df_new.iterrows():
                    if row['Harga_Baru'] > 0:
                        st.session_state.master_prices[str(row['Uraian']).lower()] = float(row['Harga_Baru'])
                        if str(row['Kode']) != "-" and str(row['Kode']) != "nan":
                            st.session_state.master_prices[str(row['Kode'])] = float(row['Harga_Baru'])
                        count += 1
                st.success(f"✅ {count} Harga Baru Diupdate!")

        # --- KOLOM 2: TEMPLATE VOLUME (RAB) ---
        with c2:
            st.subheader("2. Template RAB (Volume)")
            st.caption("Daftar semua pekerjaan dari file analisa. Isi volumenya untuk menghitung total.")
            
            # Generate Daftar Pekerjaan dari Analisa yang diupload
            job_list = []
            for job_name in st.session_state.analisa_jobs.keys():
                # Coba pecahkan kode dan nama
                parts = job_name.split(' - ', 1)
                kode = parts[0] if len(parts) > 1 else "-"
                uraian = parts[1] if len(parts) > 1 else job_name
                job_list.append({
                    'Kode_Analisa': kode,
                    'Uraian_Pekerjaan': uraian,
                    'Volume': 0.0
                })
            
            df_boq = pd.DataFrame(job_list)
            
            st.download_button("⬇️ Download Template RAB (Volume)", 
                             df_boq.to_csv(index=False).encode('utf-8'), 
                             "Template_RAB.csv", "text/csv")
            
            # Upload Balik RAB
            st.session_state.boq_data = None
            upload_boq = st.file_uploader("Upload Template RAB (Terisi)", type='csv')
            if upload_boq:
                st.session_state.boq_data = pd.read_csv(upload_boq)
                st.success("✅ Data Volume Diterima!")

# --- TAB 3: HASIL PERHITUNGAN ---
with tab3:
    if 'boq_data' in st.session_state and st.session_state.boq_data is not None:
        st.header("💰 Rekapitulasi Anggaran Biaya (RAB)")
        
        # Proses Hitung
        rab_rows = []
        total_proyek = 0
        
        # Progress Bar
        progress_bar = st.progress(0)
        total_items = len(st.session_state.boq_data)
        
        for idx, row in st.session_state.boq_data.iterrows():
            vol = float(row['Volume'])
            if vol <= 0: continue # Skip volume 0
            
            # Reconstruct Key
            job_key = f"{row['Kode_Analisa']} - {row['Uraian_Pekerjaan']}"
            
            # Cari di Analisa (Try exact match first, then fuzzy)
            comps = st.session_state.analisa_jobs.get(job_key)
            
            # Jika key dari CSV beda dikit (misal excel auto format), coba cari partial
            if not comps:
                for k, v in st.session_state.analisa_jobs.items():
                    if str(row['Kode_Analisa']) in k:
                        comps = v
                        job_key = k # Update key
                        break
            
            if comps:
                hsp = hitung_hsp(comps, st.session_state.master_prices)
                total_harga = hsp * vol
                total_proyek += total_harga
                
                rab_rows.append({
                    "Kode": row['Kode_Analisa'],
                    "Uraian Pekerjaan": row['Uraian_Pekerjaan'],
                    "Volume": vol,
                    "HSP (Rp)": f"{hsp:,.2f}",
                    "Total Harga (Rp)": f"{total_harga:,.2f}",
                    "_raw_total": total_harga # Hidden column for sorting
                })
            
            progress_bar.progress((idx + 1) / total_items)
            
        # Tampilkan Hasil
        if rab_rows:
            df_result = pd.read_json(io.StringIO(pd.DataFrame(rab_rows).to_json())) # Trick to format
            
            st.metric("TOTAL BIAYA PROYEK", f"Rp {total_proyek:,.2f}")
            st.dataframe(df_result[['Kode', 'Uraian Pekerjaan', 'Volume', 'HSP (Rp)', 'Total Harga (Rp)']], use_container_width=True)
            
            # Download Hasil Akhir
            csv_result = pd.DataFrame(rab_rows).drop(columns=['_raw_total']).to_csv(index=False).encode('utf-8')
            st.download_button("💾 Download Hasil RAB Final (CSV)", csv_result, "Final_RAB.csv", "text/csv")
        else:
            st.warning("Belum ada item pekerjaan dengan Volume > 0.")
            
    else:
        st.info("👈 Silakan Upload Template RAB yang sudah diisi di Tab 2 untuk melihat hasil.")
