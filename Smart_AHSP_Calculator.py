import streamlit as st
import pandas as pd
import csv
import io

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Pro AHSP Calculator 2025", layout="wide")

# --- CSS AGAR TABEL LEBIH LEGA ---
st.markdown("""
<style>
    .block-container {padding-top: 2rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# --- FUNGSI 1: LOAD DATABASE HARGA (UPAH BAHAN) ---
@st.cache_data
def load_master_db(file_obj):
    """Membaca file 'Upah Bahan.csv' dengan penanganan error yang lebih kuat"""
    try:
        # Baca dulu sebagai text raw untuk mencari posisi header
        content = file_obj.getvalue().decode("utf-8", errors='ignore')
        
        # Cari baris header
        header_row = -1
        lines = content.splitlines()
        for i, line in enumerate(lines[:30]): # Cek 30 baris pertama
            if "KODE" in line.upper() and "SATUAN" in line.upper():
                header_row = i
                break
        
        if header_row == -1:
            st.error("Header 'KODE' dan 'SATUAN' tidak ditemukan di file Upah Bahan.")
            return pd.DataFrame()

        # Baca CSV mulai dari header yang ditemukan
        file_obj.seek(0)
        df = pd.read_csv(file_obj, header=header_row)
        
        # Mapping nama kolom dinamis
        col_map = {}
        for c in df.columns:
            c_up = str(c).upper()
            if "KODE" in c_up: col_map['kode'] = c
            elif "URAIAN" in c_up or "UPAH" in c_up: col_map['uraian'] = c
            elif "SATUAN" in c_up and "HARGA" not in c_up: col_map['satuan'] = c
            elif "HARGA" in c_up: col_map['harga'] = c

        # Bersihkan Data
        clean_data = []
        for _, row in df.iterrows():
            try:
                # Skip jika uraian kosong
                if pd.isna(row.get(col_map.get('uraian'))) or str(row.get(col_map.get('uraian'))).strip() == "":
                    continue
                
                kode = str(row[col_map['kode']]).strip() if pd.notna(row.get(col_map.get('kode'))) else "-"
                uraian = str(row[col_map['uraian']]).strip()
                satuan = str(row[col_map['satuan']]).strip() if pd.notna(row.get(col_map.get('satuan'))) else "-"
                
                # Parsing Harga (Format Indo: 1.000.000,00)
                harga_raw = str(row[col_map['harga']]).replace('.', '').replace(',', '.')
                try:
                    harga = float(harga_raw)
                except:
                    harga = 0

                clean_data.append({
                    'Kode': kode,
                    'Uraian': uraian,
                    'Satuan': satuan,
                    'Harga_Standar': harga
                })
            except:
                continue
                
        return pd.DataFrame(clean_data)

    except Exception as e:
        st.error(f"Error membaca Upah Bahan: {e}")
        return pd.DataFrame()

# --- FUNGSI 2: PARSING ANALISA (ANTI-BUG KOMA) ---
def parse_analysis_file(file_obj):
    """Membaca file analisa pekerjaan dengan modul CSV reader yang aman"""
    job_items = {}
    
    # Baca file sebagai string
    content = file_obj.getvalue().decode("utf-8", errors='ignore')
    
    # Gunakan csv.reader agar teks bertyoe "Pipa, Dia 2" tidak terpotong
    f = io.StringIO(content)
    reader = csv.reader(f, delimiter=',')
    
    current_job = None
    components = []
    capture = False
    
    for parts in reader:
        if not parts: continue
        
        # Bersihkan spasi di setiap kolom
        parts = [p.strip() for p in parts]
        
        # 1. Deteksi Judul Pekerjaan (Misal: 2.2.1.1)
        id_val, desc_val = None, None
        
        # Cari kolom yang formatnya angka titik angka (X.X.X)
        for i, p in enumerate(parts):
            # Syarat: Ada angka, ada titik, panjang minimal 3
            if len(p) >= 3 and p[0].isdigit() and '.' in p and len(p) < 20:
                # Cek kolom kanannya ada deskripsi panjang
                if i+1 < len(parts) and len(parts[i+1]) > 5:
                    id_val = p
                    desc_val = parts[i+1]
                    break
        
        if id_val and desc_val:
            # Simpan pekerjaan sebelumnya
            if current_job:
                job_items[current_job] = components
            
            # Mulai pekerjaan baru
            current_job = f"{id_val} - {desc_val}"
            components = []
            capture = True
            continue
            
        # 2. Ambil Komponen
        if capture and current_job:
            # Skip baris header
            line_str = "".join(parts).upper()
            if "URAIAN" in line_str or "JUMLAH" in line_str or "HARGA SATUAN" in line_str:
                continue
            
            # Cari Koefisien (Angka float sendirian di tengah)
            coeff_idx = -1
            for i, p in enumerate(parts):
                if not p: continue
                try:
                    val = float(p)
                    # Syarat koefisien: Angka wajar (0 s.d 5000), bukan No urut (1,2,3)
                    # Cek kolom kirinya (Satuan) biasanya teks pendek
                    if 0 <= val < 10000:
                        if i > 0 and 0 < len(parts[i-1]) <= 8: # Satuan biasanya pendek (OH, m3, bh)
                            coeff_idx = i
                            break
                except: pass
            
            if coeff_idx != -1:
                try:
                    koef = float(parts[coeff_idx])
                    unit = parts[coeff_idx-1]
                    
                    # Logika Nama & Kode
                    # Pola umum: [Nama] [Kode] [Satuan] [Koef]
                    # Atau:      [Nama] [Satuan] [Koef]
                    
                    col_left = parts[coeff_idx-2] if coeff_idx >= 2 else ""
                    col_left_2 = parts[coeff_idx-3] if coeff_idx >= 3 else ""
                    
                    kode = ""
                    nama = ""
                    
                    # Cek apakah kolom kiri itu kode (L.01, M.02, dsb)
                    if len(col_left) < 15 and ('.' in col_left or any(c.isdigit() for c in col_left)):
                        kode = col_left
                        nama = col_left_2
                    else:
                        nama = col_left # Tidak ada kode
                    
                    if nama:
                        components.append({
                            'uraian': nama,
                            'kode': kode,
                            'unit': unit,
                            'koef': koef
                        })
                except: pass

    # Simpan record terakhir
    if current_job:
        job_items[current_job] = components
        
    return job_items

# --- MAIN UI ---
st.title("🏗️ Smart AHSP Calculator (Final Version)")
st.caption("Support Multi-Sheet Upload & Auto-Template")

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Database Harga")
    file_master = st.file_uploader("Upload 'Upah Bahan.csv'", type='csv')
    
    price_db = {} 
    df_master = pd.DataFrame()

    if file_master:
        df_master = load_master_db(file_master)
        if not df_master.empty:
            st.success(f"✅ Master OK: {len(df_master)} item")
            
            # Template Downloader
            with st.expander("📥 Download / Upload Template Harga"):
                df_template = df_master[['Kode', 'Uraian', 'Satuan', 'Harga_Standar']].copy()
                df_template['Harga_Baru'] = 0
                st.download_button(
                    "Download Template CSV",
                    df_template.to_csv(index=False).encode('utf-8'),
                    "Template_Harga.csv",
                    "text/csv"
                )
                
                user_file = st.file_uploader("Upload Template Terisi", type='csv')
                if user_file:
                    try:
                        df_user = pd.read_csv(user_file)
                        for _, row in df_user.iterrows():
                            # Prioritas Harga Baru
                            p = float(row['Harga_Baru']) if row['Harga_Baru'] > 0 else float(row['Harga_Standar'])
                            price_db[str(row['Uraian']).lower().strip()] = p
                            if str(row['Kode']).strip() != "-":
                                price_db[str(row['Kode']).strip()] = p
                        st.info("✅ Menggunakan Harga User")
                    except:
                        st.error("Format template salah")
    
    # Jika user tidak upload template, pakai harga standar
    if not price_db and not df_master.empty:
        for _, row in df_master.iterrows():
            price_db[str(row['Uraian']).lower().strip()] = row['Harga_Standar']
            if row['Kode'] != "-":
                price_db[row['Kode']] = row['Harga_Standar']

    st.divider()
    st.header("2. File Analisa")
    files_analisa = st.file_uploader("Upload Semua File Analisa (.csv)", type='csv', accept_multiple_files=True)

# --- MAIN PAGE ---
if files_analisa and price_db:
    # Parsing semua file sekaligus
    all_jobs = {}
    for f in files_analisa:
        all_jobs.update(parse_analysis_file(f))
    
    # Filter yang kosong (kadang ada sisa header)
    all_jobs = {k: v for k, v in all_jobs.items() if len(v) > 0}
    
    st.success(f"Berhasil membaca **{len(all_jobs)} jenis pekerjaan** dari {len(files_analisa)} file.")
    
    # Pilihan
    selected_job = st.selectbox("👉 Pilih Analisa Pekerjaan:", sorted(list(all_jobs.keys())))
    volume = st.number_input("Volume Pekerjaan:", min_value=1.0, value=1.0, step=0.1)
    
    if selected_job:
        comps = all_jobs[selected_job]
        st.subheader(f"Analisa: {selected_job}")
        
        # Tabel Hitungan
        data_rows = []
        total_hsp = 0
        
        for c in comps:
            # Lookup Harga
            h = 0
            src = "Nol"
            
            # Cek Kode dulu
            if c['kode'] in price_db:
                h = price_db[c['kode']]
                src = "Kode"
            # Cek Nama
            elif c['uraian'].lower() in price_db:
                h = price_db[c['uraian'].lower()]
                src = "Nama"
            else:
                # Cek Partial
                for k, v in price_db.items():
                    if k in c['uraian'].lower():
                        h = v
                        src = "Estimasi"
                        break
            
            tot = c['koef'] * h
            total_hsp += tot
            
            data_rows.append({
                "Kode": c['kode'],
                "Uraian Komponen": c['uraian'],
                "Koef": c['koef'],
                "Satuan": c['unit'],
                "Harga Satuan": f"Rp {h:,.0f}",
                "Total": f"Rp {tot:,.0f}",
                "Match": src
            })
            
        st.dataframe(pd.DataFrame(data_rows), use_container_width=True)
        
        # Rekap
        overhead = total_hsp * 0.10
        grand_total = (total_hsp + overhead) * volume
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Biaya Dasar", f"Rp {total_hsp:,.0f}")
        c2.metric("Overhead (10%)", f"Rp {overhead:,.0f}")
        c3.metric("Harga Satuan", f"Rp {total_hsp+overhead:,.0f}")
        c4.metric("TOTAL PROYEK", f"Rp {grand_total:,.0f}", delta="Final")

elif not file_master:
    st.info("👈 Silakan upload file **Upah Bahan.csv** terlebih dahulu di sidebar.")
