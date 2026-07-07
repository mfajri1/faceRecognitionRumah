# -*- coding: utf-8 -*-
"""
SISTEM KEAMANAN PINTU: WAJAH + SUARA (EDISI KHUSUS RASPBERRY PI 3)
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
    raise SystemExit("Library 'Pillow' belum terinstall. Jalankan: pip install Pillow")

try:
    import requests
except ImportError:
    requests = None  

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("[GPIO] Berjalan dalam mode simulasi PC (Pustaka GPIO tidak terdeteksi).")

# ============================================================
# KONFIGURASI SISTEM & PIN HARDWARE
# ============================================================

DATASET_DIR = "dataset" 
USERS_FILE = "users.json"
MIN_SAMPLES = 3 
FACE_SIZE = (200, 200) 
LBPH_THRESHOLD = 70 

# OPTIMASI: Resolusi diperkecil ke 480x270 agar FPS di Raspberry Pi 3 mulus
VIDEO_DISPLAY_SIZE = (480, 270) 

COLOR_BG = "#1e1e2f"
COLOR_TEXT = "#f5f5f5"
COLOR_ACCENT = "#4c6ef5"
COLOR_ACCENT2 = "#12b886"
COLOR_DANGER = "#555555"

# --- API WhatsApp Gateway (Fonnte) ---
WA_API_URL = "https://api.fonnte.com/send"
WA_TOKEN = "RgMZQCTAy8DGLNEMqphk" 
WA_TARGET = "628136554516" 

# --- Alokasi PIN GPIO ---
RELAY_SOLENOID_PIN = 17       # Relay 1 (Solenoid Pintu)
RELAY_DISCHARGE_PIN = 27      # Relay 2 (Electric Discharge)

LED_SCANNING_PIN = 22         # LED 1 - Indikator Scanning/Standby
LED_TERDETEKSI_PIN = 23       # LED 2 - Indikator Wajah Terdaftar Cocok
LED_SALAH_PIN = 24            # LED 3 - Indikator Wajah Asing / Tidak Cocok
BUZZER_PIN = 25               # Indikator Suara Buzzer

DURASI_SOLENOID_DETIK = 4
DURASI_DISCHARGE_DETIK = 8

# Sesuaikan tipe modul elektrik Anda (LOW / HIGH Active)
RELAY_ACTIVE_LOW = True
BUZZER_ACTIVE_LOW = False

# ============================================================
# INISIALISASI KONTROL PERANGKAT KERAS
# ============================================================

if GPIO_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [RELAY_SOLENOID_PIN, RELAY_DISCHARGE_PIN, LED_SCANNING_PIN, LED_TERDETEKSI_PIN, LED_SALAH_PIN, BUZZER_PIN]:
        GPIO.setup(pin, GPIO.OUT)

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
    def run():
        for _ in range(kali):
            set_buzzer(True)
            time.sleep(0.12)
            set_buzzer(False)
            time.sleep(0.08)
    threading.Thread(target=run, daemon=True).start()

def reset_semua_komponen_standby():
    """Mengembalikan perangkat keras ke status mati total saat standby."""
    _relay_set(RELAY_SOLENOID_PIN, False)
    _relay_set(RELAY_DISCHARGE_PIN, False)
    set_led(LED_SCANNING_PIN, False)
    set_led(LED_TERDETEKSI_PIN, False)
    set_led(LED_SALAH_PIN, False)
    set_buzzer(False)

reset_semua_komponen_standby()

# Muat Pemindai Model Cascade bawaan OpenCV
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)

# ============================================================
# LOGIKA DATABASE DAN PEMROSESAN
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
            update("Menyesuaikan ambang batas kebisingan...")
            recognizer_sr.adjust_for_ambient_noise(source, duration=1)
            update("Silahkan ucapkan password anda...")
            audio = recognizer_sr.listen(source, timeout=5, phrase_time_limit=5)
    except Exception:
        return None

    update("Mengirim audio ke Cloud Google STT...")
    try:
        return recognizer_sr.recognize_google(audio, language="id-ID")
    except Exception:
        return None

# ============================================================
# ANTARMUKA GUI UTAMA (TKINTER)
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
        pesan = f"⚠️ PERINGATAN KEAMANAN ⚠️\nAda upaya pembukaan pintu gagal!\nWajah: {nama_user}\nStatus: PASSWORD SUARA SALAH."
        payload = {"target": WA_TARGET, "message": pesan, "countryCode": "62"}
        headers = {"Authorization": WA_TOKEN}
        try: requests.post(WA_API_URL, data=payload, headers=headers, timeout=5)
        except Exception: pass

    def pemicu_relay_akses_diterima(self):
        """Menyalakan Solenoid (4 detik) dan Discharge (8 detik) bersamaan di background."""
        def run_solenoid():
            _relay_set(RELAY_SOLENOID_PIN, True)
            time.sleep(DURASI_SOLENOID_DETIK)
            _relay_set(RELAY_SOLENOID_PIN, False)

        def run_discharge():
            _relay_set(RELAY_DISCHARGE_PIN, True)
            time.sleep(DURASI_DISCHARGE_DETIK)
            _relay_set(RELAY_DISCHARGE_PIN, False)

        threading.Thread(target=run_solenoid, daemon=True).start()
        threading.Thread(target=run_discharge, daemon=True).start()

    # ------------------------------------------------------------------
    # MENU UTAMA: MONITOR SCANNING
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

        tk.Label(self, text="SISTEM UTAMA (SCANNING WAJAH)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 10))
        self.su_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.su_video_label.pack(pady=5)

        self.su_status_var = tk.StringVar(value="Memuat model matematika...")
        tk.Label(self, textvariable=self.su_status_var, font=("Segoe UI", 13), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center").pack(pady=15)

        self.su_recognizer, self.su_label_map = train_model()
        if self.su_recognizer is None:
            self.su_status_var.set("Dataset kosong. Daftarkan wajah Anda terlebih dahulu.")
        else:
            self.su_status_var.set("Berdiri di depan kamera untuk mendeteksi wajah...")

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
                # Kondisi Standby Utama: LED 1 Aktif, Komponen Lain Mati
                set_led(LED_SCANNING_PIN, True)
                set_led(LED_TERDETEKSI_PIN, False)
                set_led(LED_SALAH_PIN, False)

                if len(faces) > 0:
                    # OPTIMASI: Urutkan dan ambil hanya 1 wajah paling besar terdekat
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    wajah_utama = faces[0]
                    (x, y, w, h) = wajah_utama
                    cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    self.su_try_recognize(gray, wajah_utama)

            try: self.render_frame(display, self.su_video_label)
            except tk.TclError: return

        # OPTIMASI: Interval loop diringankan ke 50ms agar CPU Raspberry Pi 3 dingin
        self.camera_after_id = self.after(50, self.update_su_camera)

    def su_try_recognize(self, gray, face_rect):
        (x, y, w, h) = face_rect
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
        label, confidence = self.su_recognizer.predict(face_img)

        if confidence < LBPH_THRESHOLD:
            nama_user = self.su_label_map.get(label)
            self.su_nama_terdeteksi = nama_user
            self.su_processing = True 
            
            # Wajah Terdaftar: LED 1 Mati, LED 2 (Terdeteksi) Menyala
            set_led(LED_SCANNING_PIN, False)
            set_led(LED_TERDETEKSI_PIN, True)
            set_led(LED_SALAH_PIN, False)

            self.su_status_var.set(f"Wajah terdeteksi: '{nama_user}'.\nMenyiapkan mikrofon...")
            threading.Thread(target=self.su_proses_password, daemon=True).start()
        else:
            # Wajah Tidak Terdaftar: LED 3 (Salah) Aktif Sesaat
            set_led(LED_SCANNING_PIN, False)
            set_led(LED_TERDETEKSI_PIN, False)
            set_led(LED_SALAH_PIN, True)
            self.su_status_var.set("ANDA BELUM TERDAFTAR (WAJAH ASING)")

    def su_proses_password(self):
        spoken_text = speech_to_text(status_callback=self.su_set_status_threadsafe)

        if spoken_text is None:
            bunyi_buzzer(3)
            self.su_finish_threadsafe("Gagal menangkap suara/suara tidak jelas.")
            return

        users = load_users()
        nama_user = self.su_nama_terdeteksi
        stored_hash = users.get(nama_user, {}).get("password")
        input_hash = hash_password(spoken_text)

        if stored_hash is not None and stored_hash == input_hash:
            # Sukses: Buzzer 1x, Relay Solenoid (4s) & Discharge (8s) Menyala
            bunyi_buzzer(1)
            self.pemicu_relay_akses_diterima()
            self.su_finish_threadsafe(f'Suara: "{spoken_text}"\n\nSELAMAT, SILAHKAN MASUK')
        else:
            # Gagal: Buzzer 3x, Kirim Notifikasi Whatsapp Ke HP Utama
            bunyi_buzzer(3)
            self.kirim_notif_wa(nama_user)
            self.su_finish_threadsafe(f'Suara: "{spoken_text}"\n\nANDA SALAH MEMASUKKAN PASSWORD')

    def su_set_status_threadsafe(self, msg):
        self.after(0, lambda: self.su_status_var.set(msg))

    def su_finish_threadsafe(self, message, delay_ms=3500):
        def task():
            self.su_status_var.set(message)
            self.after(delay_ms, self.su_reset_processing)
        self.after(0, task)

    def su_reset_processing(self):
        self.su_processing = False
        reset_semua_komponen_standby() # Reset hardware kembali ke mode padam hemat daya
        if self.su_recognizer is not None:
            self.su_status_var.set("Berdiri di depan kamera untuk mendeteksi wajah...")

    # ------------------------------------------------------------------
    # MENU KEDUA: REGISTRASI DATASET WAJAH BARU
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

        tk.Label(self, text="REGISTRASI USER BARU", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 10))

        form_frame = tk.Frame(self, bg=COLOR_BG)
        form_frame.pack(pady=5)
        tk.Label(form_frame, text="Nama:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_nama = tk.Entry(form_frame, font=("Segoe UI", 12), width=22)
        self.dw_entry_nama.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form_frame, text="Password:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_password = tk.Entry(form_frame, font=("Segoe UI", 12), width=22, show="*")
        self.dw_entry_password.grid(row=1, column=1, padx=5, pady=5)

        self.dw_btn_mulai = tk.Button(form_frame, text="Mulai Daftar", font=("Segoe UI", 11), bg=COLOR_ACCENT, fg="white", relief="flat", command=self.dw_mulai)
        self.dw_btn_mulai.grid(row=0, column=2, rowspan=2, padx=15)

        self.dw_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.dw_video_label.pack(pady=5)

        self.dw_status_var = tk.StringVar(value="Isi data form di atas untuk memulai.")
        tk.Label(self, textvariable=self.dw_status_var, font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center").pack(pady=10)

        btn_frame = tk.Frame(self, bg=COLOR_BG)
        btn_frame.pack(pady=5)
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
        self.camera_after_id = self.after(40, self.update_dw_camera)

    def dw_mulai(self):
        nama = self.dw_entry_nama.get().strip()
        password = self.dw_entry_password.get().strip()

        if nama == "" or password == "":
            self.dw_status_var.set("Form registrasi nama & password wajib diisi!")
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
        self.dw_status_var.set("Wajah siap dipindai. Silahkan klik 'Ambil Foto Sample'.")

    def dw_ambil_foto(self):
        if self.last_frame_bgr is None: return
        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            self.dw_status_var.set("Wajah tidak terdeteksi oleh sensor kamera!")
            return

        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        (x, y, w, h) = faces[0]
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)

        self.dw_sample_count += 1
        nomor_file = self.dw_offset + self.dw_sample_count
        filename = os.path.join(self.dw_user_dir, f"{self.dw_nama}_{nomor_file}.jpg")
        cv2.imwrite(filename, face_img)

        self.dw_btn_ambil.config(text=f"Ambil Foto Sample ({self.dw_sample_count}/{MIN_SAMPLES})")
        self.dw_status_var.set(f"Foto ke-{self.dw_sample_count} berhasil disimpan.")

        if self.dw_sample_count >= MIN_SAMPLES:
            self.dw_btn_ambil.config(state="disabled")
            messagebox.showinfo("Sukses", f"Registrasi wajah '{self.dw_nama}' selesai!")
            self.build_sistem_utama()

# ============================================================
# RUN TRIGGER PROGRAM
# ============================================================
if __name__ == "__main__":
    app = App()
    app.mainloop()
