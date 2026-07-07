# # -*- coding: utf-8 -*-
# """
# SISTEM DETEKSI WAJAH + PASSWORD SUARA (VERSI GUI)
# ====================================================

# Saat program dibuka, langsung tampil halaman "SISTEM UTAMA" (tidak ada
# halaman menu/pilihan terpisah). Di pojok kanan atas terdapat 2 tombol:
# "Daftar Wajah" dan "✕ Keluar".

# Sistem Utama:
#    - Kamera tampil langsung, deteksi & pengenalan wajah berjalan OTOMATIS
#      terus-menerus tanpa perlu klik tombol apapun.
#    - Begitu wajah terdaftar terdeteksi -> langsung muncul notifikasi
#      "Wajah terdeteksi: <nama>" dan sistem otomatis merekam suara lewat
#      microphone untuk password (speech-to-text):
#        - Benar  -> "SELAMAT, SILAHKAN MASUK" + Relay 1 (GPIO) membuka
#                    solenoid pintu selama beberapa detik, lalu tertutup lagi.
#        - Salah  -> "ANDA SALAH MEMASUKKAN PASSWORD" + notifikasi WhatsApp
#                    terkirim SAAT ITU JUGA + Relay 2 (GPIO) menggetarkan
#                    motor vibrasi di gagang pintu (simulasi "kesetrum" yang
#                    100% aman disentuh, untuk keperluan demo skripsi).
#    - Jika wajah TIDAK terdaftar -> tampil "ANDA BELUM TERDAFTAR".

# Daftar Wajah Baru (tombol di kanan atas):
#    - Isi Nama + Password (diketik, bukan suara, karena ini dipakai sebagai
#      "kunci" yang nanti dicocokkan dengan ucapan saat verifikasi).
#    - Ambil minimal 3 foto sample wajah lewat kamera.
#    - Struktur folder dataset: dataset/<nama_user>/<foto-foto>.jpg
#    - Tombol "Sistem Utama" di kanan atas untuk kembali.

# Kebutuhan library (lihat requirements.txt):
#     pip install opencv-contrib-python SpeechRecognition PyAudio numpy Pillow requests

# Catatan instalasi PyAudio di Windows (jika "pip install pyaudio" gagal):
#     pip install pipwin
#     pipwin install pyaudio
# """

# import os
# import json
# import hashlib
# import threading
# import time

# import cv2
# import numpy as np
# import speech_recognition as sr

# import tkinter as tk
# from tkinter import messagebox

# try:
#     from PIL import Image, ImageTk
# except ImportError:
#     raise SystemExit(
#         "Library 'Pillow' belum terinstall.\n"
#         "Jalankan: pip install Pillow"
#     )

# try:
#     import requests
# except ImportError:
#     requests = None  # fitur notifikasi WA otomatis nonaktif jika belum terinstall

# try:
#     import RPi.GPIO as GPIO
#     GPIO_AVAILABLE = True
# except ImportError:
#     GPIO_AVAILABLE = False
#     print(
#         "[GPIO] Library 'RPi.GPIO' tidak ditemukan (program mungkin tidak "
#         "berjalan di Raspberry Pi). Fitur relay/vibrasi otomatis dinonaktifkan, "
#         "fitur kamera & suara tetap berjalan normal."
#     )

# # ============================================================
# # KONFIGURASI / KONSTANTA
# # ============================================================

# DATASET_DIR = "dataset"            # dataset/<nama_user>/foto.jpg
# USERS_FILE = "users.json"          # menyimpan hash password tiap user
# MIN_SAMPLES = 3                    # minimal sample wajah per user
# FACE_SIZE = (200, 200)             # ukuran standar wajah setelah di-crop
# LBPH_THRESHOLD = 70                # ambang confidence LBPH (makin kecil = makin yakin cocok)
# VIDEO_DISPLAY_SIZE = (480, 270)    # ukuran tampilan video di GUI

# COLOR_BG = "#1e1e2f"
# COLOR_TEXT = "#f5f5f5"
# COLOR_ACCENT = "#4c6ef5"
# COLOR_ACCENT2 = "#12b886"
# COLOR_DANGER = "#555555"

# # --- Konfigurasi WhatsApp Gateway (Fonnte) ---
# # Daftar & dapatkan token di https://fonnte.com
# # Notifikasi dikirim SETIAP kali password salah (tidak menunggu beberapa kali).
# WA_API_URL = "https://api.fonnte.com/send"
# WA_TOKEN = "RgMZQCTAy8DGLNEMqphk"       # ganti dengan token Fonnte milik Anda
# WA_TARGET = "628136554516"             # nomor WA tujuan notifikasi (format: 62xxxxxxxxxx)

# # --- Konfigurasi GPIO Raspberry Pi (relay) ---
# # Relay 1: solenoid pintu -> aktif 4 detik saat password BENAR
# # Relay 2: motor vibrasi di gagang pintu -> aktif saat password SALAH
# #          (simulasi efek "kesetrum" yang 100% aman disentuh, untuk demo skripsi)
# RELAY_SOLENOID_PIN = 17
# RELAY_VIBRASI_PIN = 27

# DURASI_SOLENOID_DETIK = 4
# DURASI_VIBRASI_DETIK = 2.5

# # Ganti ke False kalau modul relay 2-channel Anda aktif saat GPIO HIGH (bukan LOW).
# # Cara cek: aktifkan True dulu, lihat relay klik nyala/tidak; kalau kebalik, ubah ke False.
# RELAY_ACTIVE_LOW = True

# if GPIO_AVAILABLE:
#     GPIO.setmode(GPIO.BCM)
#     GPIO.setup(RELAY_SOLENOID_PIN, GPIO.OUT)
#     GPIO.setup(RELAY_VIBRASI_PIN, GPIO.OUT)


# def _relay_set(pin, aktif):
#     """Set kondisi relay; otomatis menyesuaikan modul aktif LOW atau HIGH."""
#     if not GPIO_AVAILABLE:
#         return
#     if aktif:
#         GPIO.output(pin, GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH)
#     else:
#         GPIO.output(pin, GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW)


# # Pastikan semua relay OFF saat program baru dijalankan.
# _relay_set(RELAY_SOLENOID_PIN, False)
# _relay_set(RELAY_VIBRASI_PIN, False)

# # Haar Cascade untuk deteksi wajah (bawaan OpenCV)
# CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
# face_cascade = cv2.CascadeClassifier(CASCADE_PATH)


# # ============================================================
# # UTILITAS UMUM (sama seperti versi console)
# # ============================================================

# def pastikan_folder_dataset():
#     os.makedirs(DATASET_DIR, exist_ok=True)


# def load_users():
#     if not os.path.exists(USERS_FILE):
#         return {}
#     with open(USERS_FILE, "r", encoding="utf-8") as f:
#         try:
#             return json.load(f)
#         except json.JSONDecodeError:
#             return {}


# def save_users(users):
#     with open(USERS_FILE, "w", encoding="utf-8") as f:
#         json.dump(users, f, indent=2, ensure_ascii=False)


# def hash_password(teks):
#     """Normalisasi teks (huruf kecil, hapus spasi) lalu hash dengan SHA-256."""
#     normalisasi = teks.strip().lower().replace(" ", "")
#     return hashlib.sha256(normalisasi.encode("utf-8")).hexdigest()


# def train_model():
#     """Membaca semua foto di folder dataset, lalu melatih model LBPH."""
#     if not os.path.exists(DATASET_DIR):
#         return None, None

#     faces = []
#     labels = []
#     label_map = {}
#     current_label = 0

#     for nama_user in sorted(os.listdir(DATASET_DIR)):
#         user_path = os.path.join(DATASET_DIR, nama_user)
#         if not os.path.isdir(user_path):
#             continue

#         file_foto = [
#             f for f in os.listdir(user_path)
#             if f.lower().endswith((".jpg", ".jpeg", ".png"))
#         ]
#         if not file_foto:
#             continue

#         label_map[current_label] = nama_user
#         for nama_file in file_foto:
#             path_foto = os.path.join(user_path, nama_file)
#             img = cv2.imread(path_foto, cv2.IMREAD_GRAYSCALE)
#             if img is None:
#                 continue
#             img = cv2.resize(img, FACE_SIZE)
#             faces.append(img)
#             labels.append(current_label)

#         current_label += 1

#     if len(faces) == 0:
#         return None, None

#     recognizer = cv2.face.LBPHFaceRecognizer_create()
#     recognizer.train(faces, np.array(labels))
#     return recognizer, label_map


# def speech_to_text(status_callback=None):
#     """Merekam suara dari microphone -> teks (Google STT, bahasa Indonesia).
#     status_callback(msg) dipanggil untuk memberi update ke GUI (opsional)."""

#     def update(msg):
#         if status_callback:
#             status_callback(msg)

#     recognizer_sr = sr.Recognizer()

#     try:
#         with sr.Microphone() as source:
#             update("Menyesuaikan suara latar belakang...")
#             recognizer_sr.adjust_for_ambient_noise(source, duration=1)
#             update("Silahkan ucapkan password anda sekarang...")
#             audio = recognizer_sr.listen(source, timeout=6, phrase_time_limit=6)
#     except sr.WaitTimeoutError:
#         update("Tidak ada suara terdeteksi (timeout).")
#         return None
#     except OSError as e:
#         update(f"Microphone tidak ditemukan / tidak bisa diakses: {e}")
#         return None

#     update("Memproses suara...")
#     try:
#         teks = recognizer_sr.recognize_google(audio, language="id-ID")
#         return teks
#     except sr.UnknownValueError:
#         update("Suara tidak dapat dikenali, mohon ucapkan lebih jelas.")
#         return None
#     except sr.RequestError as e:
#         update(f"Gagal terhubung ke layanan speech recognition: {e}")
#         return None


# # ============================================================
# # APLIKASI GUI (TKINTER)
# # ============================================================

# class App(tk.Tk):
#     def __init__(self):
#         super().__init__()
#         self.title("Sistem Deteksi Wajah + Password Suara")
#         self.geometry("780x680")
#         self.resizable(False, False)
#         self.configure(bg=COLOR_BG)
#         self.protocol("WM_DELETE_WINDOW", self.on_close)

#         pastikan_folder_dataset()

#         self.cam = None
#         self.camera_after_id = None
#         self.last_frame_bgr = None

#         self.build_sistem_utama()

#     # ------------------------------------------------------------------
#     # HELPER UMUM
#     # ------------------------------------------------------------------
#     def clear_window(self):
#         if self.camera_after_id is not None:
#             self.after_cancel(self.camera_after_id)
#             self.camera_after_id = None
#         self.release_camera()
#         for widget in self.winfo_children():
#             widget.destroy()

#     def start_camera(self):
#         if self.cam is None:
#             self.cam = cv2.VideoCapture(0)

#     def release_camera(self):
#         if self.cam is not None:
#             self.cam.release()
#             self.cam = None

#     def render_frame(self, frame_bgr, label_widget):
#         if not label_widget.winfo_exists():
#             return
#         frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
#         frame_rgb = cv2.resize(frame_rgb, VIDEO_DISPLAY_SIZE)
#         img = Image.fromarray(frame_rgb)
#         imgtk = ImageTk.PhotoImage(image=img)
#         label_widget.imgtk = imgtk  # simpan referensi agar tidak di-garbage-collect
#         label_widget.configure(image=imgtk)

#     def on_close(self):
#         self.release_camera()
#         if GPIO_AVAILABLE:
#             _relay_set(RELAY_SOLENOID_PIN, False)
#             _relay_set(RELAY_VIBRASI_PIN, False)
#             GPIO.cleanup()
#         self.destroy()

#     # ------------------------------------------------------------------
#     # NOTIFIKASI WHATSAPP (saat password salah)
#     # ------------------------------------------------------------------
#     def kirim_notif_wa(self, nama_user):
#         """Mengirim notifikasi WA via Fonnte. Dipanggil setiap kali password
#         salah (bukan setelah beberapa kali). Method ini dipanggil dari
#         background thread (su_proses_password), jadi aman walau request
#         HTTP-nya butuh waktu beberapa saat -> GUI tidak freeze."""

#         if requests is None:
#             print("[WA] Library 'requests' belum terinstall, notifikasi WA dilewati.")
#             return

#         pesan = (
#             "⚠️ PERINGATAN KEAMANAN ⚠️\n\n"
#             "Ada upaya masuk ke sistem!\n"
#             f"Wajah terdeteksi: {nama_user}\n"
#             "Status: ANDA SALAH MEMASUKKAN PASSWORD SUARA.\n\n"
#             "Mohon periksa sistem jika ini bukan Anda."
#         )
#         payload = {
#             "target": WA_TARGET,
#             "message": pesan,
#             "countryCode": "62",
#         }
#         headers = {"Authorization": WA_TOKEN}

#         try:
#             response = requests.post(WA_API_URL, data=payload, headers=headers, timeout=5)
#             print("[WA] Respon Fonnte:", response.text)
#         except Exception as e:
#             print(f"[WA] Gagal mengirim notifikasi WhatsApp: {e}")

#     # ------------------------------------------------------------------
#     # RELAY 1: SOLENOID PINTU (saat login berhasil)
#     # ------------------------------------------------------------------
#     def aktifkan_relay(self, nama_user):
#         """Dipanggil saat wajah + password suara BENAR.
#         Membuka solenoid pintu selama DURASI_SOLENOID_DETIK, lalu menutup
#         kembali otomatis. Dijalankan di background thread terpisah (lihat
#         su_proses_password) supaya tidak menahan/blocking status GUI."""
#         print(f"[RELAY] Solenoid terbuka untuk user: {nama_user}")
#         _relay_set(RELAY_SOLENOID_PIN, True)
#         time.sleep(DURASI_SOLENOID_DETIK)
#         _relay_set(RELAY_SOLENOID_PIN, False)
#         print("[RELAY] Solenoid tertutup kembali.")

#     # ------------------------------------------------------------------
#     # RELAY 2: MOTOR VIBRASI DI GAGANG PINTU (saat password salah)
#     # ------------------------------------------------------------------
#     def aktifkan_efek_salah(self, nama_user):
#         """Dipanggil saat password suara SALAH.
#         Menggetarkan motor vibrasi yang ditempel di gagang pintu, untuk
#         mensimulasikan efek 'kesetrum' secara aman (tanpa arus listrik
#         masuk ke tubuh sama sekali -> cocok untuk demo skripsi).
#         Dijalankan di background thread terpisah."""
#         print(f"[VIBRASI] Efek getar (simulasi kesetrum) aktif untuk: {nama_user}")
#         _relay_set(RELAY_VIBRASI_PIN, True)
#         time.sleep(DURASI_VIBRASI_DETIK)
#         _relay_set(RELAY_VIBRASI_PIN, False)
#         print("[VIBRASI] Efek getar berhenti.")

#     # ------------------------------------------------------------------
#     # HALAMAN: SISTEM UTAMA (LANGSUNG TAMPIL SAAT PROGRAM DIBUKA)
#     # ------------------------------------------------------------------
#     def build_sistem_utama(self):
#         self.clear_window()

#         self.su_recognizer = None
#         self.su_label_map = None
#         self.su_nama_terdeteksi = None
#         self.su_processing = False  # True saat sedang verifikasi password (mencegah deteksi ganda)

#         # --- Bar atas: tombol Daftar & Keluar di pojok kanan atas ---
#         top_bar = tk.Frame(self, bg=COLOR_BG)
#         top_bar.pack(fill="x", side="top")

#         tk.Button(
#             top_bar, text="✕ Keluar", font=("Segoe UI", 10, "bold"),
#             bg=COLOR_DANGER, fg="white", relief="flat",
#             padx=10, pady=4, command=self.on_close
#         ).pack(side="right", padx=15, pady=15)

#         tk.Button(
#             top_bar, text="Daftar Wajah", font=("Segoe UI", 10, "bold"),
#             bg=COLOR_ACCENT2, fg="white", relief="flat",
#             padx=10, pady=4, command=self.build_daftar_wajah
#         ).pack(side="right", padx=0, pady=15)

#         tk.Label(
#             self, text="SISTEM UTAMA", font=("Segoe UI", 18, "bold"),
#             bg=COLOR_BG, fg=COLOR_TEXT
#         ).pack(pady=(0, 15))

#         self.su_video_label = tk.Label(self, bg="black",
#                                         width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
#         self.su_video_label.pack(pady=10)

#         self.su_status_var = tk.StringVar(value="Mempersiapkan kamera & model wajah...")
#         tk.Label(
#             self, textvariable=self.su_status_var, font=("Segoe UI", 13),
#             bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center"
#         ).pack(pady=15)

#         self.su_recognizer, self.su_label_map = train_model()
#         if self.su_recognizer is None:
#             self.su_status_var.set(
#                 "Dataset wajah masih kosong.\nSilahkan daftar wajah dahulu lewat tombol 'Daftar Wajah' di kanan atas."
#             )
#         else:
#             self.su_status_var.set("Arahkan wajah ke kamera...")

#         self.start_camera()
#         self.update_su_camera()

#     def update_su_camera(self):
#         if self.cam is None:
#             return
#         ret, frame = self.cam.read()
#         if ret:
#             self.last_frame_bgr = frame.copy()
#             display = frame.copy()
#             gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
#             faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
#             # JIKA ADA WAJAH TERDETEKSI, CARI HANYA 1 WAJAH TERBESAR
#             if len(faces) > 0:
#                 # Mengurutkan berdasarkan luas wajah (width * height) dari besar ke kecil
#                 faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
#                 wajah_utama = faces[0]  # Ambil wajah indeks ke-0 (terbesar)
                
#                 (x, y, w, h) = wajah_utama
#                 # Gambar kotak hanya untuk 1 wajah utama ini
#                 cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)

#                 # Deteksi & pengenalan otomatis untuk wajah utama tersebut
#                 if not self.su_processing and self.su_recognizer is not None:
#                     self.su_try_recognize(gray, wajah_utama)

#             try:
#                 self.render_frame(display, self.su_video_label)
#             except tk.TclError:
#                 return

#         self.camera_after_id = self.after(30, self.update_su_camera)

#     def su_try_recognize(self, gray, face_rect):
#         (x, y, w, h) = face_rect
#         face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
#         label, confidence = self.su_recognizer.predict(face_img)

#         if confidence < LBPH_THRESHOLD:
#             nama_user = self.su_label_map.get(label)
#             self.su_nama_terdeteksi = nama_user
#             self.su_processing = True  # kunci, supaya tidak trigger berulang saat proses suara
#             self.su_status_var.set(
#                 f"Wajah terdeteksi: '{nama_user}'.\nSilahkan ucapkan password anda..."
#             )
#             threading.Thread(target=self.su_proses_password, daemon=True).start()
#         else:
#             self.su_status_var.set("ANDA BELUM TERDAFTAR")

#     def su_proses_password(self):
#         """Berjalan di background thread (dipanggil dari su_try_recognize),
#         supaya proses dengarkan microphone & request WA tidak membuat GUI
#         freeze."""

#         spoken_text = speech_to_text(status_callback=self.su_set_status_threadsafe)

#         if spoken_text is None:
#             self.su_finish_threadsafe(
#                 "Password tidak dikenali lewat suara.\nSilahkan coba lagi..."
#             )
#             return

#         users = load_users()
#         nama_user = self.su_nama_terdeteksi
#         stored_hash = users.get(nama_user, {}).get("password")
#         input_hash = hash_password(spoken_text)

#         if stored_hash is not None and stored_hash == input_hash:
#             # Password benar -> buka solenoid pintu (di thread terpisah,
#             # supaya status "SELAMAT, SILAHKAN MASUK" langsung muncul tanpa
#             # menunggu 4 detik solenoid selesai)
#             threading.Thread(target=self.aktifkan_relay, args=(nama_user,), daemon=True).start()
#             self.su_finish_threadsafe(f'Suara terdengar: "{spoken_text}"\n\nSELAMAT, SILAHKAN MASUK')
#         else:
#             # Password salah -> kirim notifikasi WA + getarkan gagang pintu
#             self.kirim_notif_wa(nama_user)
#             threading.Thread(target=self.aktifkan_efek_salah, args=(nama_user,), daemon=True).start()
#             self.su_finish_threadsafe(
#                 f'Suara terdengar: "{spoken_text}"\n\n'
#                 "ANDA SALAH MEMASUKKAN PASSWORD\n📲 Notifikasi sudah dikirim ke WhatsApp."
#             )

#     def su_set_status_threadsafe(self, msg):
#         """Update status secara langsung (dipanggil dari background thread)."""
#         self.after(0, lambda: self.su_status_var.set(msg))

#     def su_finish_threadsafe(self, message, delay_ms=3000):
#         """Tampilkan hasil akhir, lalu otomatis kembali ke mode deteksi setelah beberapa saat."""
#         def task():
#             self.su_status_var.set(message)
#             self.after(delay_ms, self.su_reset_processing)
#         self.after(0, task)

#     def su_reset_processing(self):
#         """Hanya membuka kunci & reset status. TIDAK perlu menjadwalkan ulang
#         update_su_camera() di sini -> loop kamera sudah berjalan terus dari
#         update_su_camera() itu sendiri."""
#         self.su_processing = False
#         if self.su_recognizer is not None:
#             self.su_status_var.set("Arahkan wajah ke kamera...")

#     # ------------------------------------------------------------------
#     # HALAMAN: DAFTAR WAJAH BARU
#     # ------------------------------------------------------------------
#     def build_daftar_wajah(self):
#         self.clear_window()

#         self.dw_nama = None
#         self.dw_user_dir = None
#         self.dw_offset = 0
#         self.dw_sample_count = 0

#         # --- Bar atas: tombol Sistem Utama & Keluar di pojok kanan atas ---
#         top_bar = tk.Frame(self, bg=COLOR_BG)
#         top_bar.pack(fill="x", side="top")

#         tk.Button(
#             top_bar, text="✕ Keluar", font=("Segoe UI", 10, "bold"),
#             bg=COLOR_DANGER, fg="white", relief="flat",
#             padx=10, pady=4, command=self.on_close
#         ).pack(side="right", padx=15, pady=15)

#         tk.Button(
#             top_bar, text="Sistem Utama", font=("Segoe UI", 10, "bold"),
#             bg=COLOR_ACCENT, fg="white", relief="flat",
#             padx=10, pady=4, command=self.build_sistem_utama
#         ).pack(side="right", padx=0, pady=15)

#         tk.Label(
#             self, text="DAFTAR WAJAH BARU", font=("Segoe UI", 18, "bold"),
#             bg=COLOR_BG, fg=COLOR_TEXT
#         ).pack(pady=(0, 15))

#         form_frame = tk.Frame(self, bg=COLOR_BG)
#         form_frame.pack(pady=5)

#         tk.Label(form_frame, text="Nama:", font=("Segoe UI", 12),
#                  bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=5, pady=5)
#         self.dw_entry_nama = tk.Entry(form_frame, font=("Segoe UI", 12), width=22)
#         self.dw_entry_nama.grid(row=0, column=1, padx=5, pady=5)

#         tk.Label(form_frame, text="Password:", font=("Segoe UI", 12),
#                  bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=5, pady=5)
#         self.dw_entry_password = tk.Entry(form_frame, font=("Segoe UI", 12), width=22, show="*")
#         self.dw_entry_password.grid(row=1, column=1, padx=5, pady=5)

#         self.dw_btn_mulai = tk.Button(
#             form_frame, text="Mulai Pendaftaran", font=("Segoe UI", 11),
#             bg=COLOR_ACCENT, fg="white", relief="flat", command=self.dw_mulai
#         )
#         self.dw_btn_mulai.grid(row=0, column=2, rowspan=2, padx=15)

#         self.dw_video_label = tk.Label(self, bg="black",
#                                         width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
#         self.dw_video_label.pack(pady=10)

#         self.dw_status_var = tk.StringVar(value="Isi nama & password, lalu klik 'Mulai Pendaftaran'.")
#         tk.Label(
#             self, textvariable=self.dw_status_var, font=("Segoe UI", 12),
#             bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center"
#         ).pack(pady=10)

#         btn_frame = tk.Frame(self, bg=COLOR_BG)
#         btn_frame.pack(pady=10)

#         self.dw_btn_ambil = tk.Button(
#             btn_frame, text=f"Ambil Foto Sample (0/{MIN_SAMPLES})", font=("Segoe UI", 12),
#             bg=COLOR_ACCENT2, fg="white", relief="flat", width=24, state="disabled",
#             command=self.dw_ambil_foto
#         )
#         self.dw_btn_ambil.grid(row=0, column=0, padx=10)

#         self.start_camera()
#         self.update_dw_camera()

#     def update_dw_camera(self):
#         if self.cam is None:
#             return
#         ret, frame = self.cam.read()
#         if ret:
#             self.last_frame_bgr = frame.copy()
#             display = frame.copy()
#             gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
#             faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
#             # HANYA GAMBAR KOTAK UNTUK 1 WAJAH TERBESAR
#             if len(faces) > 0:
#                 faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
#                 (x, y, w, h) = faces[0]
#                 cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
#             try:
#                 self.render_frame(display, self.dw_video_label)
#             except tk.TclError:
#                 return
#         self.camera_after_id = self.after(20, self.update_dw_camera)

#     def dw_mulai(self):
#         nama = self.dw_entry_nama.get().strip()
#         password = self.dw_entry_password.get().strip()

#         if nama == "":
#             self.dw_status_var.set("Nama tidak boleh kosong.")
#             return
#         if password == "":
#             self.dw_status_var.set("Password tidak boleh kosong.")
#             return

#         pastikan_folder_dataset()
#         user_dir = os.path.join(DATASET_DIR, nama)
#         os.makedirs(user_dir, exist_ok=True)

#         users = load_users()
#         users[nama] = {"password": hash_password(password)}
#         save_users(users)

#         file_lama = [
#             f for f in os.listdir(user_dir)
#             if f.lower().endswith((".jpg", ".jpeg", ".png"))
#         ]

#         self.dw_nama = nama
#         self.dw_user_dir = user_dir
#         self.dw_offset = len(file_lama)
#         self.dw_sample_count = 0

#         self.dw_entry_nama.config(state="disabled")
#         self.dw_entry_password.config(state="disabled")
#         self.dw_btn_mulai.config(state="disabled")
#         self.dw_btn_ambil.config(state="normal", text=f"Ambil Foto Sample (0/{MIN_SAMPLES})")

#         self.dw_status_var.set(f"Posisikan wajah '{nama}' di kamera, lalu klik 'Ambil Foto Sample'.")

#     def dw_ambil_foto(self):
#         if self.last_frame_bgr is None:
#             return

#         gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
#         faces = face_cascade.detectMultiScale(gray, 1.3, 5)

#         if len(faces) == 0:
#             self.dw_status_var.set("Wajah tidak terdeteksi, posisikan ulang wajah anda.")
#             return

#         # URUTKAN DAN AMBIL 1 WAJAH TERBESAR
#         faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
#         (x, y, w, h) = faces[0]
#         face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)

#         self.dw_sample_count += 1
#         nomor_file = self.dw_offset + self.dw_sample_count
#         filename = os.path.join(self.dw_user_dir, f"{self.dw_nama}_{nomor_file}.jpg")
#         cv2.imwrite(filename, face_img)

#         self.dw_btn_ambil.config(text=f"Ambil Foto Sample ({self.dw_sample_count}/{MIN_SAMPLES})")
#         self.dw_status_var.set(f"Sample {self.dw_sample_count}/{MIN_SAMPLES} disimpan -> {filename}")

#         if self.dw_sample_count >= MIN_SAMPLES:
#             self.dw_btn_ambil.config(state="disabled")
#             self.dw_status_var.set(f"Pendaftaran '{self.dw_nama}' selesai dengan {self.dw_sample_count} sample!")
#             messagebox.showinfo(
#                 "Berhasil",
#                 f"Wajah '{self.dw_nama}' berhasil didaftarkan dengan {self.dw_sample_count} sample."
#             )


# # ============================================================
# # ENTRY POINT
# # ============================================================

# if __name__ == "__main__":
#     app = App()
#     app.mainloop()

# -*- coding: utf-8 -*-
"""
SISTEM DETEKSI WAJAH + PASSWORD SUARA (VERSI GUI + FULL HARDWARE)
================================================================
"""

import os
import json
import hashlib
import threading
import time

import cv2
import numpy as np
import speech_recognition as sr

import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    raise SystemExit(
        "Library 'Pillow' belum terinstall.\n"
        "Jalankan: pip install Pillow"
    )

try:
    import requests
except ImportError:
    requests = None  

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print(
        "[GPIO] Library 'RPi.GPIO' tidak ditemukan (program tidak berjalan di Raspberry Pi).\n"
        "Fitur komponen fisik dinonaktifkan, simulasi logika GUI tetap berjalan normal."
    )

# ============================================================
# KONFIGURASI / KONSTANTA
# ============================================================

DATASET_DIR = "dataset" 
USERS_FILE = "users.json"
MIN_SAMPLES = 3 
FACE_SIZE = (200, 200) 
LBPH_THRESHOLD = 70 
VIDEO_DISPLAY_SIZE = (480, 270) # Resolusi dioptimalkan untuk kelancaran Raspi

COLOR_BG = "#1e1e2f"
COLOR_TEXT = "#f5f5f5"
COLOR_ACCENT = "#4c6ef5"
COLOR_ACCENT2 = "#12b886"
COLOR_DANGER = "#555555"

# --- Konfigurasi WhatsApp Gateway (Fonnte) ---
WA_API_URL = "https://api.fonnte.com/send"
WA_TOKEN = "RgMZQCTAy8DGLNEMqphk" 
WA_TARGET = "628136554516" 

# --- Alokasi Pin GPIO Raspberry Pi ---
RELAY_SOLENOID_PIN = 17       # Relay 1 (Solenoid Pintu)
RELAY_DISCHARGE_PIN = 27      # Relay 2 (Electric Discharge)

LED_SCANNING_PIN = 22         # LED 1 - Proses Pembacaan Wajah (Mencari Wajah)
LED_TERDETEKSI_PIN = 23       # LED 2 - Wajah Terdaftar Terdeteksi
LED_SALAH_PIN = 24            # LED 3 - Wajah Tidak Terdaftar / Asing
BUZZER_PIN = 25               # Active Buzzer

DURASI_SOLENOID_DETIK = 4
DURASI_DISCHARGE_DETIK = 8

# Ubah ke False jika modul relay atau buzzer Anda bertipe Active HIGH
RELAY_ACTIVE_LOW = True
BUZZER_ACTIVE_LOW = False

# ============================================================
# INISIALISASI HARDWARE GPIO
# ============================================================

if GPIO_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    # Setup Output Pins
    GPIO.setup(RELAY_SOLENOID_PIN, GPIO.OUT)
    GPIO.setup(RELAY_DISCHARGE_PIN, GPIO.OUT)
    GPIO.setup(LED_SCANNING_PIN, GPIO.OUT)
    GPIO.setup(LED_TERDETEKSI_PIN, GPIO.OUT)
    GPIO.setup(LED_SALAH_PIN, GPIO.OUT)
    GPIO.setup(BUZZER_PIN, GPIO.OUT)

def _relay_set(pin, aktif):
    if not GPIO_AVAILABLE: return
    if aktif:
        GPIO.output(pin, GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH)
    else:
        GPIO.output(pin, GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW)

def set_led(pin, aktif):
    if not GPIO_AVAILABLE: return
    GPIO.output(pin, GPIO.HIGH if aktif else GPIO.LOW)

def set_buzzer(aktif):
    if not GPIO_AVAILABLE: return
    if aktif:
        GPIO.output(BUZZER_PIN, GPIO.LOW if BUZZER_ACTIVE_LOW else GPIO.HIGH)
    else:
        GPIO.output(BUZZER_PIN, GPIO.HIGH if BUZZER_ACTIVE_LOW else GPIO.LOW)

def bunyi_buzzer(kali):
    """Membunyikan buzzer dalam background thread agar GUI tidak lag."""
    def run():
        for _ in range(kali):
            set_buzzer(True)
            time.sleep(0.15)
            set_buzzer(False)
            time.sleep(0.1)
    threading.Thread(target=run, daemon=True).start()

def reset_semua_komponen_standby():
    """Mematikan seluruh komponen (LED, Buzzer, Relay) ke kondisi standby (Mati semua)."""
    _relay_set(RELAY_SOLENOID_PIN, False)
    _relay_set(RELAY_DISCHARGE_PIN, False)
    set_led(LED_SCANNING_PIN, False)
    set_led(LED_TERDETEKSI_PIN, False)
    set_led(LED_SALAH_PIN, False)
    set_buzzer(False)

# Inisialisasi awal mode standby saat aplikasi pertama kali dibuka
reset_semua_komponen_standby()

# Load Haar Cascade
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)

# ============================================================
# UTILITAS UMUM
# ============================================================

def pastikan_folder_dataset():
    os.makedirs(DATASET_DIR, exist_ok=True)

def load_users():
    if not os.path.exists(USERS_FILE): return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except json.JSONDecodeError: return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def hash_password(teks):
    normalisasi = teks.strip().lower().replace(" ", "")
    return hashlib.sha256(normalisasi.encode("utf-8")).hexdigest()

def train_model():
    if not os.path.exists(DATASET_DIR): return None, None
    faces, labels, label_map = [], [], {}
    current_label = 0

    for nama_user in sorted(os.listdir(DATASET_DIR)):
        user_path = os.path.join(DATASET_DIR, nama_user)
        if not os.path.isdir(user_path): continue
        file_foto = [f for f in os.listdir(user_path) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        if not file_foto: continue

        label_map[current_label] = nama_user
        for nama_file in file_foto:
            path_foto = os.path.join(user_path, nama_file)
            img = cv2.imread(path_foto, cv2.IMREAD_GRAYSCALE)
            if img is None: continue
            img = cv2.resize(img, FACE_SIZE)
            faces.append(img)
            labels.append(current_label)
        current_label += 1

    if len(faces) == 0: return None, None
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(faces, np.array(labels))
    return recognizer, label_map

def speech_to_text(status_callback=None):
    def update(msg):
        if status_callback: status_callback(msg)
    recognizer_sr = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            update("Menyesuaikan suara latar belakang...")
            recognizer_sr.adjust_for_ambient_noise(source, duration=1)
            update("Silahkan ucapkan password anda sekarang...")
            audio = recognizer_sr.listen(source, timeout=6, phrase_time_limit=6)
    except Exception as e:
        update(f"Error Microphone: {e}")
        return None

    update("Memproses suara...")
    try:
        return recognizer_sr.recognize_google(audio, language="id-ID")
    except Exception:
        return None

# ============================================================
# APLIKASI GUI (TKINTER)
# ============================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sistem Deteksi Wajah + Password Suara")
        self.geometry("780x680")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        pastikan_folder_dataset()
        self.cam = None
        self.camera_after_id = None
        self.last_frame_bgr = None
        self.build_sistem_utama()

    def clear_window(self):
        if self.camera_after_id is not None:
            self.after_cancel(self.camera_after_id)
            self.camera_after_id = None
        self.release_camera()
        for widget in self.winfo_children():
            widget.destroy()

    def start_camera(self):
        if self.cam is None: self.cam = cv2.VideoCapture(0)

    def release_camera(self):
        if self.cam is not None:
            self.cam.release()
            self.cam = None

    def render_frame(self, frame_bgr, label_widget):
        if not label_widget.winfo_exists(): return
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb = cv2.resize(frame_rgb, VIDEO_DISPLAY_SIZE)
        img = Image.fromarray(frame_rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        label_widget.imgtk = imgtk
        label_widget.configure(image=imgtk)

    def on_close(self):
        self.release_camera()
        reset_semua_komponen_standby()
        if GPIO_AVAILABLE: GPIO.cleanup()
        self.destroy()

    def kirim_notif_wa(self, nama_user):
        if requests is None: return
        pesan = (
            "⚠️ PERINGATAN KEAMANAN ⚠️\n\n"
            "Ada upaya masuk ke sistem!\n"
            f"Wajah terdeteksi: {nama_user}\n"
            "Status: ANDA SALAH MEMASUKKAN PASSWORD SUARA.\n\n"
            "Mohon periksa sistem jika ini bukan Anda."
        )
        payload = {"target": WA_TARGET, "message": pesan, "countryCode": "62"}
        headers = {"Authorization": WA_TOKEN}
        try: requests.post(WA_API_URL, data=payload, headers=headers, timeout=5)
        except Exception as e: print(f"[WA] Gagal kirim: {e}")

    # --- Fungsi Kontrol Output Relay Saat Akses Diterima ---
    def aktifkan_relay_pintu_sukses(self):
        """Menyalakan Relay Solenoid (4s) dan Relay Electric Discharge (8s) secara bersamaan."""
        def run_solenoid():
            print("[RELAY] Solenoid Aktif (4 Detik)")
            _relay_set(RELAY_SOLENOID_PIN, True)
            time.sleep(DURASI_SOLENOID_DETIK)
            _relay_set(RELAY_SOLENOID_PIN, False)
            print("[RELAY] Solenoid Mati")

        def run_discharge():
            print("[RELAY] Electric Discharge Aktif (8 Detik)")
            _relay_set(RELAY_DISCHARGE_PIN, True)
            time.sleep(DURASI_DISCHARGE_DETIK)
            _relay_set(RELAY_DISCHARGE_PIN, False)
            print("[RELAY] Electric Discharge Mati")

        # Menggunakan thread terpisah agar pewaktuan 4 detik dan 8 detik berjalan bersamaan
        threading.Thread(target=run_solenoid, daemon=True).start()
        threading.Thread(target=run_discharge, daemon=True).start()

    # ------------------------------------------------------------------
    # HALAMAN: SISTEM UTAMA
    # ------------------------------------------------------------------
    def build_sistem_utama(self):
        self.clear_window()
        self.su_recognizer = None
        self.su_label_map = None
        self.su_nama_terdeteksi = None
        self.su_processing = False 

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")

        tk.Button(top_bar, text="✕ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
        tk.Button(top_bar, text="Daftar Wajah", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT2, fg="white", relief="flat", padx=10, pady=4, command=self.build_daftar_wajah).pack(side="right", padx=0, pady=15)

        tk.Label(self, text="SISTEM UTAMA", font=("Segoe UI", 18, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 15))
        self.su_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.su_video_label.pack(pady=10)

        self.su_status_var = tk.StringVar(value="Mempersiapkan...")
        tk.Label(self, textvariable=self.su_status_var, font=("Segoe UI", 13), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center").pack(pady=15)

        self.su_recognizer, self.su_label_map = train_model()
        if self.su_recognizer is None:
            self.su_status_var.set("Dataset wajah masih kosong.\nSilahkan daftar wajah dahulu.")
        else:
            self.su_status_var.set("Arahkan wajah ke kamera...")

        self.start_camera()
        self.update_su_camera()

    def update_su_camera(self):
        if self.cam is None: return
        ret, frame = self.cam.read()
        if ret:
            self.last_frame_bgr = frame.copy()
            display = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if not self.su_processing:
                # --- INDIKATOR STANDBY / SCANNING ---
                # Selama tidak dalam proses kunci verifikasi suara, LED 1 aktif, LED 2 & 3 mati.
                set_led(LED_SCANNING_PIN, True)
                set_led(LED_TERDETEKSI_PIN, False)
                set_led(LED_SALAH_PIN, False)

                if len(faces) > 0:
                    # Ambil hanya 1 wajah terbesar (Fokus utama)
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    wajah_utama = faces[0]
                    
                    (x, y, w, h) = wajah_utama
                    cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    self.su_try_recognize(gray, wajah_utama)

            try: self.render_frame(display, self.su_video_label)
            except tk.TclError: return

        self.camera_after_id = self.after(30, self.update_su_camera)

    def su_try_recognize(self, gray, face_rect):
        (x, y, w, h) = face_rect
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
        label, confidence = self.su_recognizer.predict(face_img)

        if confidence < LBPH_THRESHOLD:
            nama_user = self.su_label_map.get(label)
            self.su_nama_terdeteksi = nama_user
            self.su_processing = True 
            
            # --- INDIKATOR WAJAH TERDAFTAR ---
            set_led(LED_SCANNING_PIN, False)
            set_led(LED_TERDETEKSI_PIN, True)   # LED 2 aktif
            set_led(LED_SALAH_PIN, False)

            self.su_status_var.set(f"Wajah terdeteksi: '{nama_user}'.\nSilahkan ucapkan password anda...")
            threading.Thread(target=self.su_proses_password, daemon=True).start()
        else:
            # --- INDIKATOR WAJAH SALAH / ASING ---
            set_led(LED_SCANNING_PIN, False)
            set_led(LED_TERDETEKSI_PIN, False)
            set_led(LED_SALAH_PIN, True)        # LED 3 aktif
            self.su_status_var.set("ANDA BELUM TERDAFTAR")

    def su_proses_password(self):
        spoken_text = speech_to_text(status_callback=self.su_set_status_threadsafe)

        if spoken_text is None:
            # Jika suara kosong/timeout, dianggap input salah -> Buzzer 3 kali
            bunyi_buzzer(3)
            self.su_finish_threadsafe("Password tidak dikenali lewat suara.\nSilahkan coba lagi...")
            return

        users = load_users()
        nama_user = self.su_nama_terdeteksi
        stored_hash = users.get(nama_user, {}).get("password")
        input_hash = hash_password(spoken_text)

        if stored_hash is not None and stored_hash == input_hash:
            # --- PASSWORD BENAR ---
            bunyi_buzzer(1)  # Buzzer berbunyi 1 kali
            self.aktifkan_relay_pintu_sukses() # Relay 1 (4s) & Relay 2 (8s) aktif bersamaan
            self.su_finish_threadsafe(f'Suara terdengar: "{spoken_text}"\n\nSELAMAT, SILAHKAN MASUK \n\n "{nama_user}"')
        else:
            # --- PASSWORD SALAH ---
            bunyi_buzzer(3)  # Buzzer berbunyi 3 kali
            self.kirim_notif_wa(nama_user) # Kirim laporan ke WhatsApp
            self.su_finish_threadsafe(f'Suara terdengar: "{spoken_text}"\n\nANDA SALAH MEMASUKKAN PASSWORD\n📲 Notifikasi terkirim ke WhatsApp.')

    def su_set_status_threadsafe(self, msg):
        self.after(0, lambda: self.su_status_var.set(msg))

    def su_finish_threadsafe(self, message, delay_ms=3000):
        def task():
            self.su_status_var.set(message)
            self.after(delay_ms, self.su_reset_processing)
        self.after(0, task)

    def su_reset_processing(self):
        self.su_processing = False
        reset_semua_komponen_standby() # --- KEMBALI KE MODE STANDBY (Semua Mati) ---
        if self.su_recognizer is not None:
            self.su_status_var.set("Arahkan wajah ke kamera...")

    # ------------------------------------------------------------------
    # HALAMAN: DAFTAR WAJAH BARU
    # ------------------------------------------------------------------
    def build_daftar_wajah(self):
        self.clear_window()
        reset_semua_komponen_standby()

        self.dw_nama = None
        self.dw_user_dir = None
        self.dw_offset = 0
        self.dw_sample_count = 0

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")

        tk.Button(top_bar, text="✕ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
        tk.Button(top_bar, text="Sistem Utama", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT, fg="white", relief="flat", padx=10, pady=4, command=self.build_sistem_utama).pack(side="right", padx=0, pady=15)

        tk.Label(self, text="DAFTAR WAJAH BARU", font=("Segoe UI", 18, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 15))

        form_frame = tk.Frame(self, bg=COLOR_BG)
        form_frame.pack(pady=5)

        tk.Label(form_frame, text="Nama:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_nama = tk.Entry(form_frame, font=("Segoe UI", 12), width=22)
        self.dw_entry_nama.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form_frame, text="Password:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_password = tk.Entry(form_frame, font=("Segoe UI", 12), width=22, show="*")
        self.dw_entry_password.grid(row=1, column=1, padx=5, pady=5)

        self.dw_btn_mulai = tk.Button(form_frame, text="Mulai Pendaftaran", font=("Segoe UI", 11), bg=COLOR_ACCENT, fg="white", relief="flat", command=self.dw_mulai)
        self.dw_btn_mulai.grid(row=0, column=2, rowspan=2, padx=15)

        self.dw_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.dw_video_label.pack(pady=10)

        self.dw_status_var = tk.StringVar(value="Isi nama & password, lalu klik 'Mulai Pendaftaran'.")
        tk.Label(self, textvariable=self.dw_status_var, font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center").pack(pady=10)

        btn_frame = tk.Frame(self, bg=COLOR_BG)
        btn_frame.pack(pady=10)

        self.dw_btn_ambil = tk.Button(btn_frame, text=f"Ambil Foto Sample (0/{MIN_SAMPLES})", font=("Segoe UI", 12), bg=COLOR_ACCENT2, fg="white", relief="flat", width=24, state="disabled", command=self.dw_ambil_foto)
        self.dw_btn_ambil.grid(row=0, column=0, padx=10)

        self.start_camera()
        self.update_dw_camera()

    def update_dw_camera(self):
        if self.cam is None: return
        ret, frame = self.cam.read()
        if ret:
            self.last_frame_bgr = frame.copy()
            display = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if len(faces) > 0:
                faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                (x, y, w, h) = faces[0]
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
            try: self.render_frame(display, self.dw_video_label)
            except tk.TclError: return
        self.camera_after_id = self.after(20, self.update_dw_camera)

    def dw_mulai(self):
        nama = self.dw_entry_nama.get().strip()
        password = self.dw_entry_password.get().strip()

        if nama == "" or password == "":
            self.dw_status_var.set("Nama/Password tidak boleh kosong.")
            return

        pastikan_folder_dataset()
        user_dir = os.path.join(DATASET_DIR, nama)
        os.makedirs(user_dir, exist_ok=True)

        users = load_users()
        users[nama] = {"password": hash_password(password)}
        save_users(users)

        file_lama = [f for f in os.listdir(user_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]

        self.dw_nama = nama
        self.dw_user_dir = user_dir
        self.dw_offset = len(file_lama)
        self.dw_sample_count = 0

        self.dw_entry_nama.config(state="disabled")
        self.dw_entry_password.config(state="disabled")
        self.dw_btn_mulai.config(state="disabled")
        self.dw_btn_ambil.config(state="normal", text=f"Ambil Foto Sample (0/{MIN_SAMPLES})")
        self.dw_status_var.set(f"Posisikan wajah '{nama}' di kamera, lalu klik 'Ambil Foto Sample'.")

    def dw_ambil_foto(self):
        if self.last_frame_bgr is None: return

        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            self.dw_status_var.set("Wajah tidak terdeteksi, posisikan ulang wajah anda.")
            return

        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        (x, y, w, h) = faces[0]
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)

        self.dw_sample_count += 1
        nomor_file = self.dw_offset + self.dw_sample_count
        filename = os.path.join(self.dw_user_dir, f"{self.dw_nama}_{nomor_file}.jpg")
        cv2.imwrite(filename, face_img)

        self.dw_btn_ambil.config(text=f"Ambil Foto Sample ({self.dw_sample_count}/{MIN_SAMPLES})")
        self.dw_status_var.set(f"Sample {self.dw_sample_count}/{MIN_SAMPLES} disimpan.")

        if self.dw_sample_count >= MIN_SAMPLES:
            self.dw_btn_ambil.config(state="disabled")
            messagebox.showinfo("Berhasil", f"Wajah '{self.dw_nama}' berhasil didaftarkan.")
            self.build_sistem_utama()

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app = App()
    app.mainloop()