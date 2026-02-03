import streamlit as st
import pandas as pd

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Simple AHSP Calculator", layout="wide")

# --- 1. FUNGSI UNTUK MEMECAH STRING ---
# Contoh Input: "Pekerja 0.75;Mandor 0.025"
# Output: [{'nama': 'Pekerja', 'koef': 0.75}, {'nama': 'Mandor', 'koef': 0.025}]
def parse_komponen(text_str):
    if pd.isna(text_str) or str(text_str).strip() in ["-", "", "nan"]:
        return []
    
    items = []
    # Pisahkan berdasarkan titik koma (;)
    parts = str(text_str).split(';')
    
    for p in parts:
        p = p.strip()
        if p and p != "-":
            # Ambil angka di bagian paling belakang sebagai koefisien
            # Logic: Pisahkan string dari spasi terakhir
            split_result = p.rpartition(' ') 
            
            nama = split_result[0].strip() # Bagian depan (Nama)
            angka_str = split_result[2].strip() # Bagian belakang (Angka)
            
            try:
                # Coba ubah string angka menjadi float
                koef = float(angka_str)
                if nama:
                    items.append({'nama': nama, 'koef': koef})
            except:
                # Jika format salah (misal tidak ada angka), lewati
                continue
    return items

# --- 2. FUNGSI LOAD DATABASE HARGA ---
@st.cache_data
def load_harga(file):
    try:
        df = pd.read_csv(file)
        # Pastikan kolom ada
        if 'nama' not in df.columns or 'harga' not in df.columns:
            st.error("File Harga harus punya kolom: 'nama' dan 'harga'")
            return {}
            
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
        st.error(f"Gagal membaca file harga: {e}")
        return {}

# --- 3. TAMPILAN UTAMA (UI) ---
st.title("⚡ Kalkulator AHSP (Versi Ringkas)")
st.markdown("Aplikasi perhitungan RAB cepat berbasis data CSV sederhana.")

# Sidebar untuk Upload
st.sidebar.header("📂 Upload Data")
file_ahsp = st.sidebar.file_uploader("1. File Analisa (ahsp1.csv)", type="csv")
file_harga = st.sidebar.file_uploader("2. File Harga (harga_fix.csv)", type="csv")

# --- LOGIKA UTAMA ---
if file_ahsp and file_harga:
    # Load Data Harga ke Memory
    db_harga = load_harga(file_harga)
    
    if db_harga:
        st.sidebar.success(f"✅ Database Harga: {len(db_harga)} item")

        # Load Data AHSP
        try:
            df_ahsp = pd.read_csv(file_ahsp)
            # Pastikan kolom kunci ada
            if 'uraian' not in df_ahsp.columns:
                st.error("File AHSP harus ada kolom 'uraian'.")
                st.stop()
                
            # Dropdown Menu Pilihan Pekerjaan
            daftar_pekerjaan = df_ahsp['uraian'].unique()
            pilihan = st.selectbox("👉 Pilih Jenis Pekerjaan:", daftar_pekerjaan)

            # Proses Hitung Saat Pekerjaan Dipilih
            if pilihan:
                # Ambil satu baris data yang dipilih user
                row = df_ahsp[df_ahsp['uraian'] == pilihan].iloc[0]
                
                # Tampilkan Info Dasar
                satuan = row.get('satuan', '-')
                kode = row.get('kode', '-')
                st.subheader(f"Analisa: {pilihan}")
                st.caption(f"Kode: {kode} | Satuan: {satuan}")

                # List penampung komponen
                all_components = []
                
                # Loop untuk kolom Tenaga, Bahan, Alat
                # Pastikan nama kolom di CSV lowercase: tenaga, bahan, alat
                col_names = [c for c in df_ahsp.columns if c.lower() in ['tenaga', 'bahan', 'alat']]
                
                for col in col_names:
                    isi_cell = row[col]
                    komponen_list = parse_komponen(isi_cell)
                    for k in komponen_list:
                        k['jenis'] = col.upper() # Label Jenis (TENAGA/BAHAN/ALAT)
                        all_components.append(k)

                if not all_components:
                    st.warning("Item ini tidak memiliki rincian komponen (kosong).")
                else:
                    # Buat Tabel Rincian Biaya
                    rincian_data = []
                    total_biaya_dasar = 0

                    for item in all_components:
                        nama_item = item['nama']
                        koef = item['koef']
                        
                        # Cari harga di database (pakai huruf kecil semua biar cocok)
                        harga_satuan = db_harga.get(nama_item.lower(), 0)
                        
                        # Cek status harga
                        if harga_satuan == 0:
                            status = "❌ Harga Nol/Tidak Ada"
                        else:
                            status = "✅ Ada"

                        total_per_item = koef * harga_satuan
                        total_biaya_dasar += total_per_item

                        rincian_data.append({
                            "Jenis": item['jenis'],
                            "Komponen": nama_item,
                            "Koefisien": koef,
                            "Harga Satuan": f"Rp {harga_satuan:,.0f}",
                            "Total Harga": f"Rp {total_per_item:,.0f}",
                            "Status": status
                        })

                    # Tampilkan Tabel Dataframe
                    st.table(pd.DataFrame(rincian_data))

                    # Hitung Rekapitulasi Akhir
                    overhead_percent = 0.10 # 10% Overhead (Bisa diubah)
                    nilai_overhead = total_biaya_dasar * overhead_percent
                    total_akhir = total_biaya_dasar + nilai_overhead

                    st.markdown("---")
                    col1, col2, col3 = st.columns(3)
                    
                    col1.metric("Biaya Dasar (HSP)", f"Rp {total_biaya_dasar:,.2f}")
                    col2.metric("Overhead & Profit (10%)", f"Rp {nilai_overhead:,.2f}")
                    col3.metric("HARGA SATUAN TOTAL", f"Rp {total_akhir:,.2f}", delta="Final")

        except Exception as e:
            st.error(f"Terjadi kesalahan saat membaca file AHSP: {e}")
else:
    st.info("👋 Selamat Datang! Silakan upload file `ahsp1.csv` dan `harga_fix.csv` di menu sebelah kiri.")
