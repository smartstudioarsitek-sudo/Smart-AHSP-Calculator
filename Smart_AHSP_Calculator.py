import streamlit as st
import pandas as pd
import io
import re

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="Smart AHSP Calculator",
    page_icon="🏗️",
    layout="wide"
)

# Custom CSS untuk tampilan yang lebih rapi
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stTable {
        background-color: #ffffff;
        border-radius: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. FUNGSI UTILITIES & PARSING ---

def clean_currency(value):
    """Mengubah string format Indonesia (1.000.000,00) ke float Python"""
    if pd.isna(value) or value == '':
        return 0.0
    s = str(value).strip()
    # Hapus pemisah ribuan (titik) dan ganti desimal (koma) jadi titik
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0

@st.cache_data
def load_resource_db(upah_file):
    """
    Membaca Database Upah & Bahan.
    Mendeteksi otomatis baris header dengan mencari kolom 'KODE' dan 'SATUAN'.
    """
    try:
        # Baca 20 baris pertama untuk mencari header
        df_temp = pd.read_csv(upah_file, header=None, nrows=20)
        
        header_row_index = -1
        # Loop cari baris yang mengandung keyword
        for i, row in df_temp.iterrows():
            row_str = row.astype(str).str.upper().tolist()
            if any("KODE" in x for x in row_str) and any("SATUAN" in x for x in row_str):
                header_row_index = i
                break
        
        if header_row_index == -1:
            return None, {}, {}

        # Baca ulang dengan header yang benar
        df = pd.read_csv(upah_file, header=header_row_index)
        
        # Normalisasi nama kolom
        col_map = {}
        for c in df.columns:
            c_upper = str(c).upper().strip()
            if "KODE" in c_upper: col_map['code'] = c
            elif "URAIAN" in c_upper or "UPAH" in c_upper or "MATERIAL" in c_upper: col_map['name'] = c
            elif "SATUAN" in c_upper and "HARGA" not in c_upper: col_map['unit'] = c
            elif "HARGA" in c_upper: col_map['price'] = c

        # Mapping data
        resource_map_by_code = {} # Pencarian cepat by Kode
        resource_map_by_name = {} # Pencarian cepat by Nama (lowercase)

        count = 0
        for _, row in df.iterrows():
            try:
                name_col = col_map.get('name')
                price_col = col_map.get('price')
                unit_col = col_map.get('unit')
                code_col = col_map.get('code')

                if not name_col or pd.isna(row[name_col]): continue

                nama = str(row[name_col]).strip()
                harga = clean_currency(row[price_col]) if price_col else 0
                satuan = str(row[unit_col]).strip() if unit_col and pd.notna(row[unit_col]) else ""
                kode = str(row[code_col]).strip() if code_col and pd.notna(row[code_col]) else ""

                item_data = {
                    'nama': nama,
                    'harga': harga,
                    'satuan': satuan,
                    'kode': kode
                }

                if kode and len(kode) > 1:
                    resource_map_by_code[kode] = item_data
                
                # Simpan juga by nama untuk fallback jika kode tidak ada/berubah
                resource_map_by_name[nama.lower()] = item_data
                count += 1
            except Exception:
                continue

        return df, resource_map_by_code, resource_map_by_name

    except Exception as e:
        st.error(f"Error membaca file Upah: {e}")
        return None, {}, {}

def parse_analysis_file(file_content):
    """
    Parsing file Analisa CSV yang kompleks.
    Struktur file CSV AHSP biasanya:
    Job Header (ID, Nama) -> Components (Koefisien, Bahan, dll) -> Total -> Job Header berikutnya
    """
    job_items = {}
    lines = file_content.splitlines()
    
    current_job_id = None
    current_job_name = None
    components = []
    
    # Regex untuk mendeteksi ID Pekerjaan (misal: 1.1.1, 2.3.4.1)
    # Harus diawali angka, mengandung titik, minimal panjang 3
    job_id_pattern = re.compile(r'^"?(\d+\.[\d\.]+)"?')

    for line in lines:
        # Pisahkan CSV manual (handle quote sederhana)
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        
        # --- 1. DETEKSI HEADER PEKERJAAN ---
        # Mencari baris yang kolom pertamanya adalah ID pekerjaan (e.g., 2.2.1.1)
        # dan kolom berikutnya berisi deskripsi pekerjaan
        match = job_id_pattern.match(parts[0]) if parts else None
        
        # Validasi tambahan: ID harus punya minimal 2 segmen (x.y) dan deskripsi ada
        if match and len(parts) > 1 and parts[1]:
            # Simpan pekerjaan sebelumnya jika ada
            if current_job_id and components:
                full_title = f"{current_job_id} - {current_job_name}"
                job_items[full_title] = components
            
            # Reset untuk pekerjaan baru
            current_job_id = match.group(1)
            current_job_name = parts[1]
            components = []
            continue

        # --- 2. DETEKSI KOMPONEN (DATA BARIS) ---
        if current_job_id:
            # Skip baris header/sub-header/total/overhead
            line_upper = line.upper()
            keywords_to_skip = [
                "URAIAN", "TENAGA KERJA", "BAHAN", "PERALATAN", 
                "JUMLAH HARGA", "BIAYA UMUM", "HARGA SATUAN PEKERJAAN",
                "CATATAN", "REVISI", "NO,URAIAN"
            ]
            if any(k in line_upper for k in keywords_to_skip):
                continue
            
            # Skip baris kosong
            if all(p == '' for p in parts):
                continue

            try:
                # Logika Heuristik untuk menemukan Koefisien
                # Biasanya struktur baris komponen: [No, Uraian, Kode, Satuan, Koefisien, Harga, Jumlah]
                # Kita cari angka float kecil (< 1000) yang merupakan koefisien.
                
                nama_item = ""
                kode_item = ""
                satuan_item = ""
                koefisien = 0.0
                
                found_coeff = False
                coeff_idx = -1

                # Cari kolom koefisien (biasanya kolom ke-4 atau ke-5)
                # Loop dari belakang biar lebih aman kadang ada kolom kosong di depan
                # Atau loop forward, cari angka valid
                
                for i in range(len(parts)):
                    val_str = parts[i]
                    if not val_str: continue
                    
                    # Cek apakah ini angka (potensi koefisien)
                    # Koefisien jarang > 10000 (kecuali paku/kawat dalam gram, tapi biasanya kecil)
                    if val_str.replace('.', '').isdigit() or ('.' in val_str and val_str.replace('.', '', 1).isdigit()):
                        try:
                            val = float(val_str)
                            # Validasi heuristik: Koefisien biasanya > 0. Harga biasanya besar.
                            # Kita anggap koefisien kalau di kolom sebelumnya ada satuan (string pendek)
                            prev_col = parts[i-1] if i > 0 else ""
                            if 0 < len(prev_col) < 10 and not prev_col.replace('.', '').isdigit(): 
                                koefisien = val
                                coeff_idx = i
                                found_coeff = True
                                break
                        except:
                            pass
                
                if found_coeff:
                    satuan_item = parts[coeff_idx-1]
                    
                    # Nama item biasanya di index 1 atau 2, atau coeff_idx-2 / coeff_idx-3
                    # Kode item kadang ada, kadang tidak
                    
                    # Coba ambil text di sebelah kiri satuan
                    candidates = [p for p in parts[:coeff_idx-1] if p]
                    
                    if candidates:
                        # Kandidat terakhir biasanya Kode (jika format L.01) atau bagian akhir nama
                        last_cand = candidates[-1]
                        
                        # Cek apakah kandidat terakhir terlihat seperti kode (L.01, M.01, angka pendek)
                        if len(last_cand) < 10 and ('.' in last_cand or last_cand.isalnum()):
                            kode_item = last_cand
                            if len(candidates) > 1:
                                nama_item = candidates[-2]
                            else:
                                # Kadang tidak ada nama terpisah jika parsing kacau
                                nama_item = "Unknown Component" 
                        else:
                            nama_item = last_cand # Tidak ada kode, langsung nama
                            
                        # Fallback jika nama kosong tapi ada di index awal
                        if not nama_item or len(nama_item) < 3:
                            # Cari string terpanjang di kiri
                            valid_strings = [s for s in parts[:coeff_idx-1] if len(s) > 3]
                            if valid_strings:
                                nama_item = valid_strings[0]

                    if nama_item and koefisien > 0:
                        components.append({
                            'nama': nama_item,
                            'kode': kode_item,
                            'satuan': satuan_item,
                            'koef': koefisien
                        })

            except Exception:
                pass

    # Jangan lupa simpan job terakhir
    if current_job_id and components:
        full_title = f"{current_job_id} - {current_job_name}"
        job_items[full_title] = components

    return job_items

# --- 3. LOGIKA UTAMA APLIKASI ---

st.title("🏗️ Smart AHSP Calculator")
st.markdown("Aplikasi perhitungan Analisa Harga Satuan Pekerjaan berdasarkan file CSV Bina Marga/Cipta Karya.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Upload Data Dasar")
    st.info("Upload file **'Upah Bahan.csv'** yang berisi daftar harga dasar.")
    upah_file = st.file_uploader("File Upah & Bahan", type=['csv'], key="upah")

    st.divider()

    st.header("2. Upload Analisa")
    st.info("Upload satu atau banyak file **Analisa (.csv)** (e.g., Persiapan, Beton, dll).")
    analisa_files = st.file_uploader("File Analisa", type=['csv'], accept_multiple_files=True, key="analisa")

    st.divider()
    overhead_pct = st.slider("Overhead & Profit (%)", 0, 25, 10, 1) / 100

# --- MAIN CONTENT ---

if upah_file and analisa_files:
    # 1. Load Database Upah
    with st.spinner("Memuat Database Upah & Bahan..."):
        df_upah, res_by_code, res_by_name = load_resource_db(upah_file)
    
    if df_upah is None:
        st.stop()
    
    st.sidebar.success(f"✅ Database: {len(res_by_name)} item harga dimuat.")

    # 2. Parse Analisa Files
    all_jobs = {}
    with st.spinner("Menganalisa struktur file AHSP..."):
        for f in analisa_files:
            content = f.getvalue().decode("utf-8", errors='replace')
            jobs = parse_analysis_file(content)
            all_jobs.update(jobs)
    
    if not all_jobs:
        st.error("❌ Tidak ditemukan item pekerjaan yang valid. Pastikan format CSV sesuai standar AHSP (Kolom ID Pekerjaan e.g., 2.2.1.1 di awal baris).")
        st.stop()

    st.success(f"Berhasil memuat **{len(all_jobs)}** jenis pekerjaan analisis.")

    # 3. User Interface Selection
    st.markdown("### 📝 Simulasi Perhitungan")
    
    col_sel1, col_sel2 = st.columns([3, 1])
    with col_sel1:
        selected_job_name = st.selectbox("Pilih Item Pekerjaan:", options=sorted(list(all_jobs.keys())))
    with col_sel2:
        volume = st.number_input("Volume Pekerjaan:", min_value=0.0, value=1.0, step=0.1)

    # 4. Calculation Engine
    if selected_job_name:
        components = all_jobs[selected_job_name]
        
        detail_data = []
        total_base_cost = 0.0
        
        # Iterasi setiap komponen dalam analisa
        for comp in components:
            nama_analisa = comp['nama']
            kode_analisa = comp['kode']
            koef = comp['koef']
            
            harga_dasar = 0.0
            sumber_harga = "❌ Tidak Ditemukan"
            match_status = "error" # error, warning, success

            # STRATEGI PENCARIAN HARGA
            
            # 1. Cari berdasarkan KODE (Paling Akurat)
            if kode_analisa and kode_analisa in res_by_code:
                harga_dasar = res_by_code[kode_analisa]['harga']
                sumber_harga = "✅ Match Kode"
                match_status = "success"
                # Update nama biar lebih lengkap dari db
                nama_display = res_by_code[kode_analisa]['nama']
            
            # 2. Cari berdasarkan NAMA PERSIS
            elif nama_analisa.lower() in res_by_name:
                harga_dasar = res_by_name[nama_analisa.lower()]['harga']
                sumber_harga = "✅ Match Nama"
                match_status = "success"
                nama_display = nama_analisa

            # 3. Cari berdasarkan NAMA PARSIAL (Fallback)
            else:
                # Cari apakah token nama ada di database
                best_match = None
                nama_clean = nama_analisa.lower().replace('"', '').strip()
                
                # Coba cari yang mengandung kata kunci
                for db_name, db_data in res_by_name.items():
                    if nama_clean in db_name or db_name in nama_clean:
                        # Pastikan kemiripan panjang string wajar (menghindari match 'Pasir' ke 'Pasir Urug')
                        if abs(len(nama_clean) - len(db_name)) < 15:
                            best_match = db_data
                            break
                
                if best_match:
                    harga_dasar = best_match['harga']
                    sumber_harga = "⚠️ Match Parsial"
                    match_status = "warning"
                    nama_display = f"{nama_analisa} (Asumsi: {best_match['nama']})"
                else:
                    nama_display = nama_analisa
                    # Cek apakah ini Tenaga Kerja (biasanya L.01, dst tapi tidak match)
                    if "pekerja" in nama_clean or "tukang" in nama_clean:
                         match_status = "error" 

            jumlah_harga = koef * harga_dasar
            total_base_cost += jumlah_harga
            
            detail_data.append({
                "Tipe": "Komponen",
                "Uraian": nama_display,
                "Kode": kode_analisa,
                "Satuan": comp['satuan'],
                "Koefisien": koef,
                "Harga Satuan": harga_dasar,
                "Jumlah Harga": jumlah_harga,
                "Status": sumber_harga
            })

        # --- 5. TAMPILAN HASIL ---
        
        # Buat DataFrame
        df_result = pd.DataFrame(detail_data)
        
        # Format Currency columns for display
        df_display = df_result.copy()
        df_display['Harga Satuan'] = df_display['Harga Satuan'].apply(lambda x: f"Rp {x:,.0f}")
        df_display['Jumlah Harga'] = df_display['Jumlah Harga'].apply(lambda x: f"Rp {x:,.0f}")

        st.markdown("#### Rincian Analisa")
        st.dataframe(
            df_display, 
            column_config={
                "Status": st.column_config.TextColumn("Status Sumber Data"),
            },
            use_container_width=True,
            hide_index=True
        )

        # Metrics
        overhead_cost = total_base_cost * overhead_pct
        hsp_total = total_base_cost + overhead_cost
        project_total = hsp_total * volume

        st.divider()
        col_res1, col_res2, col_res3 = st.columns(3)
        
        with col_res1:
            st.metric("Total Dasar (Material + Upah)", f"Rp {total_base_cost:,.2f}")
        with col_res2:
            st.metric(f"Overhead & Profit ({int(overhead_pct*100)}%)", f"Rp {overhead_cost:,.2f}")
        with col_res3:
            st.metric("Harga Satuan Pekerjaan (HSP)", f"Rp {hsp_total:,.2f}", delta="Per Unit")

        st.markdown(f"""
        <div style="background-color:#d4edda;padding:20px;border-radius:10px;text-align:center;border:1px solid #c3e6cb">
            <h2 style="color:#155724;margin:0">Total Biaya Proyek</h2>
            <p style="margin:0;font-size:1.2rem">Volume: {volume}</p>
            <h1 style="color:#155724;margin-top:10px">Rp {project_total:,.2f}</h1>
        </div>
        """, unsafe_allow_html=True)

        # Download Button
        csv_buffer = io.StringIO()
        df_result.to_csv(csv_buffer, index=False)
        st.download_button(
            label="💾 Download Rincian CSV",
            data=csv_buffer.getvalue(),
            file_name=f"Analisa_{selected_job_name[:20]}.csv",
            mime="text/csv"
        )

else:
    # Tampilan awal (Landing Page)
    st.markdown("""
    <div style="text-align:center; padding: 50px;">
        <h2>👋 Selamat Datang di Smart AHSP</h2>
        <p>Silakan upload file CSV di sidebar sebelah kiri untuk memulai perhitungan.</p>
        <p style="color:grey; font-size:0.9em">
        Sistem ini mencocokkan kode/nama komponen dari file Analisa dengan database Harga Satuan Dasar.
        </p>
    </div>
    """, unsafe_allow_html=True)
