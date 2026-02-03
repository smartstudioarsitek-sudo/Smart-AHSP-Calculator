import streamlit as st
import pandas as pd

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="RAB PUPR SE-30", layout="wide")

# --- 1. FUNGSI PARSING STRING ---
def parse_komponen(text_str):
    if pd.isna(text_str) or str(text_str).strip() in ["-", "", "nan"]:
        return []
    
    items = []
    # Pisahkan berdasarkan titik koma (;)
    parts = str(text_str).split(';')
    
    for p in parts:
        p = p.strip()
        if p and p != "-":
            # Pisahkan nama dan angka dari belakang
            split_result = p.rpartition(' ') 
            nama = split_result[0].strip()
            angka_str = split_result[2].strip()
            
            try:
                koef = float(angka_str)
                if nama:
                    items.append({'nama': nama, 'koef': koef})
            except:
                continue
    return items

# --- 2. FUNGSI LOAD HARGA ---
@st.cache_data
def load_harga(file):
    try:
        df = pd.read_csv(file)
        harga_dict = {}
        for index, row in df.iterrows():
            nama = str(row['nama']).strip().lower()
            try:
                harga = float(row['harga'])
                harga_dict[nama] = harga
            except:
                continue
        return harga_dict
    except Exception as e:
        return {}

# --- 3. UI UTAMA ---
st.title("🏗️ Kalkulator RAB - Standar PUPR (SE 30)")
st.markdown("""
Aplikasi ini menggunakan referensi:  
**SE Dirjen Bina Konstruksi No. 30/SE/Dk/2025** (Bukan Permen lama).
""")

st.divider()

# Sidebar
st.sidebar.header("📂 Basis Data")
file_ahsp = st.sidebar.file_uploader("1. File Analisa (ahsp1.csv)", type="csv")
file_harga = st.sidebar.file_uploader("2. File Harga (harga_fix.csv)", type="csv")

# --- LOGIKA UTAMA ---
if file_ahsp and file_harga:
    db_harga = load_harga(file_harga)
    
    if db_harga:
        st.sidebar.success(f"✅ Terhubung: {len(db_harga)} komponen harga")

        try:
            df_ahsp = pd.read_csv(file_ahsp)
            
            # --- BAGIAN INPUT USER ---
            col_input1, col_input2 = st.columns([3, 1])
            
            with col_input1:
                # Dropdown Menu
                daftar_pekerjaan = df_ahsp['uraian'].unique()
                pilihan = st.selectbox("👉 Pilih Analisa Pekerjaan (AHSP SE-30):", daftar_pekerjaan)
            
            with col_input2:
                # Input Volume
                row_temp = df_ahsp[df_ahsp['uraian'] == pilihan].iloc[0]
                satuan_label = row_temp.get('satuan', 'Unit')
                volume = st.number_input(f"Volume ({satuan_label})", min_value=0.0, value=1.0, step=0.1)

            # --- PROSES HITUNG ---
            if pilihan:
                row = df_ahsp[df_ahsp['uraian'] == pilihan].iloc[0]
                st.info(f"Kode Analisa: **{row.get('kode', '-')}** | Standar: SE Bina Konstruksi 30/2025")

                all_components = []
                col_names = [c for c in df_ahsp.columns if c.lower() in ['tenaga', 'bahan', 'alat']]
                
                for col in col_names:
                    isi_cell = row[col]
                    komponen_list = parse_komponen(isi_cell)
                    for k in komponen_list:
                        k['jenis'] = col.upper()
                        all_components.append(k)

                if not all_components:
                    st.warning("Data komponen kosong.")
                else:
                    # Tabel Rincian
                    rincian_data = []
                    total_hsp = 0 # Harga Satuan Pekerjaan

                    for item in all_components:
                        nama_item = item['nama']
                        koef = item['koef']
                        harga_satuan = db_harga.get(nama_item.lower(), 0)
                        
                        total_sub = koef * harga_satuan
                        total_hsp += total_sub

                        rincian_data.append({
                            "Kategori": item['jenis'],
                            "Uraian": nama_item,
                            "Koefisien": koef,
                            "Harga Satuan": f"Rp {harga_satuan:,.0f}",
                            "Jumlah Harga": f"Rp {total_sub:,.0f}"
                        })

                    st.table(pd.DataFrame(rincian_data))

                    # --- REKAPITULASI ---
                    overhead_pct = 0.10 # Overhead 10%
                    nilai_overhead = total_hsp * overhead_pct
                    harga_satuan_jadi = total_hsp + nilai_overhead
                    
                    # Total Harga Proyek (Dikali Volume)
                    total_biaya_proyek = harga_satuan_jadi * volume

                    st.markdown("### 💰 Hasil Perhitungan RAB")
                    
                    # Tampilan Metric Berjejer
                    c1, c2, c3, c4 = st.columns(4)
                    
                    c1.metric("Biaya Dasar", f"Rp {total_hsp:,.2f}")
                    c2.metric("Overhead (10%)", f"Rp {nilai_overhead:,.2f}")
                    c3.metric("Harga Satuan (HSP)", f"Rp {harga_satuan_jadi:,.2f}")
                    c4.metric(f"TOTAL BIAYA (Vol: {volume})", f"Rp {total_biaya_proyek:,.2f}", delta="Final RAB")

        except Exception as e:
            st.error(f"Error membaca file: {e}")
else:
    st.info("Silakan upload file `ahsp1.csv` dan `harga_fix.csv` di sidebar.")
