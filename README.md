# Sistem Deteksi Wajah + Password Suara

## Dua Versi Program
- **`sistem_face_password.py`** — versi console/CLI (menu teks + jendela kamera OpenCV).
- **`sistem_face_password_gui.py`** — versi **GUI (Tkinter)**, tombol-tombol klik, tanpa menu teks. **(disarankan dipakai)**

Kedua versi memakai dataset & `users.json` yang sama, jadi wajah yang sudah
didaftarkan lewat versi GUI juga bisa dipakai login di versi console (dan
sebaliknya).

## Struktur Folder (terbentuk otomatis saat program dijalankan)
```
project/
├── sistem_face_password.py
├── requirements.txt
├── users.json          <- dibuat otomatis (hash password tiap user)
└── dataset/
    ├── budi/
    │   ├── budi_1.jpg
    │   ├── budi_2.jpg
    │   └── budi_3.jpg
    └── siti/
        ├── siti_1.jpg
        ├── siti_2.jpg
        └── siti_3.jpg
```

## Instalasi

### 1. Buat Virtual Environment (Python 3.10)

**Windows** — jalankan file `setup_venv.bat` (double click, atau lewat CMD):
```bat
setup_venv.bat
```
Script ini otomatis mencari Python 3.10 (`py -3.10`), membuat folder `venv/`,
mengaktifkannya, lalu menginstall semua dependency.

Jika ingin manual:
```bat
py -3.10 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Linux / macOS** — jalankan file `setup_venv.sh`:
```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

Jika ingin manual:
```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Lain kali membuka project ini, tinggal aktifkan venv-nya saja (tidak perlu
> install ulang):
> - Windows: `venv\Scripts\activate`
> - Linux/Mac: `source venv/bin/activate`

### 2. (Alternatif) Install langsung tanpa venv
```bash
pip install -r requirements.txt
```

### Catatan khusus PyAudio (microphone)
Kadang `pip install pyaudio` gagal di Windows karena butuh compiler. Jika gagal:

```bash
pip install pipwin
pipwin install pyaudio
```

Di Linux, install dulu library sistemnya:
```bash
sudo apt-get install portaudio19-dev
pip install pyaudio
```

> Catatan: `tkinter` (untuk versi GUI) biasanya sudah bawaan Python di Windows
> dan macOS. Jika di Linux muncul error `No module named tkinter`, install:
> ```bash
> sudo apt-get install python3-tk
> ```

## Cara Menjalankan

**Versi GUI (disarankan):**
```bash
python sistem_face_password_gui.py
```
Akan terbuka jendela dengan 2 tombol: **"Sistem Utama"** dan **"Daftar Wajah Baru"**.

**Versi Console:**
```bash
python sistem_face_password.py
```

### Panduan Versi GUI

**Daftar Wajah Baru:**
1. Isi **Nama** & **Password**, klik **"Mulai Pendaftaran"**.
2. Posisikan wajah di kamera (preview langsung tampil di jendela).
3. Klik **"Ambil Foto Sample"** sebanyak 3x (progress tombol: `1/3`, `2/3`, `3/3`).
4. Muncul notifikasi "Berhasil" setelah selesai.

**Sistem Utama:**
1. Posisikan wajah di kamera, klik **"Verifikasi Wajah"**.
2. Jika wajah **tidak dikenali** -> tampil `ANDA BELUM TERDAFTAR`.
3. Jika wajah **dikenali** -> sistem otomatis merekam suara dari microphone.
   - Password **salah** -> `ANDA SALAH MEMASUKKAN PASSWORD`
   - Password **benar** -> `SELAMAT, SILAHKAN MASUK`

### Panduan Versi Console

Akan muncul menu:
```
1. Sistem Utama
2. Daftar Wajah Baru
0. Keluar
```

**Menu 2 - Daftar Wajah Baru:**
1. Masukkan nama (jadi nama folder di `dataset/`).
2. Buat password (ini yang nanti diucapkan lewat microphone saat verifikasi).
3. Kamera akan terbuka. Posisikan wajah, tekan **SPACE** untuk mengambil
   setiap sample (minimal 3 sample), **ESC** untuk membatalkan.

**Menu 1 - Sistem Utama:**
1. Kamera terbuka, posisikan wajah, tekan **SPACE** untuk verifikasi
   (**ESC** untuk batal).
2. Jika wajah **tidak dikenali** -> tampil `ANDA BELUM TERDAFTAR`.
3. Jika wajah **dikenali** -> program meminta Anda mengucapkan password
   ke microphone (speech-to-text, Bahasa Indonesia).
   - Password **benar** -> `SELAMAT, SILAHKAN MASUK`
   - Password **salah** -> `ANDA SALAH MEMASUKKAN PASSWORD`


## Catatan Teknis
- Pengenalan wajah memakai **LBPH (Local Binary Patterns Histogram)** dari
  OpenCV — cukup ringan dan tidak butuh GPU/dlib.
- Model dilatih ulang otomatis (`train_model()`) setiap kali menu
  "Sistem Utama" dijalankan, jadi wajah yang baru saja didaftarkan langsung
  bisa dipakai login tanpa restart program.
- Ambang kemiripan (`LBPH_THRESHOLD = 70`) bisa disesuaikan di bagian
  konfigurasi pada `sistem_face_password.py` — semakin kecil nilainya,
  semakin "strict" sistem mengenali wajah.
- Password disimpan dalam bentuk **hash SHA-256** di `users.json`, bukan
  teks asli.
- Karena password dimasukkan lewat suara, hasil speech-to-text bisa sedikit
  berbeda (misal kapitalisasi/spasi) — ini sudah dinormalisasi sebelum
  dibandingkan, tapi tetap ucapkan password dengan jelas dan di tempat yang
  tidak terlalu berisik.