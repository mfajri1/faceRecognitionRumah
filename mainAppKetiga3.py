"""
SISTEM KEAMANAN PINTU: WAJAH + SUARA (EDISI LCD 20X4 I2C RASPBERRY PI)
===================================================================
UPDATED: SHIFTWA INTEGRATION (IMAGE + CAPTION) & 15S COOLDOWN
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

# --- INTEGRASI LCD 20x4 I2C ---
try:
    from smbus2 import SMBus
    from RPLCD.i2c import CharLCD
    lcd = CharLCD('PCF8574', 0x27, port=1, cols=20, rows=4)
    LCD_AVAILABLE = True
    print("[LCD] LCD 20x4 I2C Terdeteksi dan Aktif.")
except Exception as e:
    LCD_AVAILABLE = False
    lcd = None
    print(f"[LCD WARNING] Gagal memuat LCD (Mode simulasi): {e}")

# ============================================================
# KONFIGURASI SISTEM & PIN HARDWARE
# ============================================================

DATASET_DIR = "dataset" 
USERS_FILE = "users.json"
MIN_SAMPLES = 3 
FACE_SIZE = (200, 200) 
LBPH_THRESHOLD = 70 

VIDEO_DISPLAY_SIZE = (480, 270) 

COLOR_BG = "#1e1e2f"
COLOR_TEXT = "#f5f5f5"
COLOR_ACCENT = "#4c6ef5"
COLOR_ACCENT2 = "#12b886"
COLOR_DANGER = "#555555"


# --- Alokasi PIN GPIO ---
RELAY_SOLENOID_PIN = 27       # Relay 1 (Solenoid Pintu) - Active Low
RELAY_DISCHARGE_PIN = 23      # Relay 2 (Electric Discharge)
BUZZER_PIN = 22               # Buzzer terhubung ke PIN 22          
LED_TERDETEKSI_PIN = 24       
LED_SALAH_PIN = 25            

DURASI_SOLENOID_DETIK = 4
DURASI_DISCHARGE_DETIK = 5    

RELAY_ACTIVE_LOW = True
BUZZER_ACTIVE_LOW = False

# ============================================================
# FUNGSI HARDWARE & LCD UTILITY
# ============================================================

def lcd_cetak(baris1="", baris2="", baris3="", baris4=""):
    if not LCD_AVAILABLE or lcd is None:
        return
    try:
        lcd.clear()
        lcd.cursor_pos = (0, 0)
        lcd.write_string(baris1[:20].center(20))
        lcd.cursor_pos = (1, 0)
        lcd.write_string(baris2[:20].center(20))
        lcd.cursor_pos = (2, 0)
        lcd.write_string(baris3[:20].center(20))
        lcd.cursor_pos = (3, 0)
        lcd.write_string(baris4[:20].center(20))
    except Exception as e:
        print(f"[LCD ERROR] Gagal menulis ke layar: {e}")

if GPIO_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [RELAY_SOLENOID_PIN, RELAY_DISCHARGE_PIN, LED_TERDETEKSI_PIN, LED_SALAH_PIN, BUZZER_PIN]:
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

def bunyi_buzzer_sync(kali):
    for _ in range(kali):
        set_buzzer(True)
        time.sleep(0.12)
        set_buzzer(False)
        time.sleep(0.08)

def reset_semua_komponen_standby():
    _relay_set(RELAY_SOLENOID_PIN, False)
    _relay_set(RELAY_DISCHARGE_PIN, False)
    set_led(LED_TERDETEKSI_PIN, False)
    set_led(LED_SALAH_PIN, False)
    set_buzzer(False)
    lcd_cetak("=== DOOR LOCK ===", "SISTEM AKTIF", "Silahkan Berdiri", "Di Depan Kamera")

CASCADE_PATH = "haarcascade_frontalface_default.xml"
PROFILE_CASCADE_PATH = "haarcascade_profileface.xml" # <- Tambahkan ini
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
profile_cascade = cv2.CascadeClassifier(PROFILE_CASCADE_PATH) # <- Tambahkan ini

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
    def update(msg, l1="", l2="", l3="", l4=""):
        if status_callback: status_callback(msg)
        lcd_cetak(l1, l2, l3, l4)
        
    recognizer_sr = sr.Recognizer()
    ID_MIC_ANDA = 2           
    SAMPLE_RATE_MIC = 48000   
    
    try:
        with sr.Microphone(device_index=ID_MIC_ANDA, sample_rate=SAMPLE_RATE_MIC) as source:
            update("Menyesuaikan ambang batas kebisingan...", "VERIFIKASI SUARA", "Mohon Tenang...", "Kalibrasi Mic...", "")
            recognizer_sr.adjust_for_ambient_noise(source, duration=0.8) 
            
            update("Silahkan ucapkan password anda...", "VERIFIKASI SUARA", "Silahkan Ucapkan", "Password Anda!", "")
            audio = recognizer_sr.listen(source, timeout=4, phrase_time_limit=4)
    except Exception as e:
        print(f"[AUDIO ERROR]: {e}")
        return None

    update("Mengirim audio ke Cloud Google STT...", "VERIFIKASI SUARA", "Memproses Audio...", "Harap Tunggu...", "")
    try:
        return recognizer_sr.recognize_google(audio, language="id-ID")
    except sr.UnknownValueError:
        update("Google STT gagal menerjemahkan.", "VERIFIKASI GAGAL", "Suara Tidak", "Jelas / Terputus", "")
        return None
    except sr.RequestError:
        update("Koneksi internet lambat / Cloud Timeout.", "VERIFIKASI GAGAL", "Koneksi Internet", "Bermasalah!", "")
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
        self.cooldown_start_time = None  # State Waktu Cooldown Keamanan
        
        reset_semua_komponen_standby()
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
        if LCD_AVAILABLE and lcd is not None:
            lcd.clear()
            lcd.write_string("Sistem Mati".center(20))
        if GPIO_AVAILABLE: GPIO.cleanup()
        self.destroy()

    # --- FUNGSI ASYNC SHIFTWA (3-STEP UPLOAD) ---
    def kirim_shiftwa_async(self, nama_user, status_akses, photo_path="pintu_log.jpg"):
        def target():
            if requests is None or not os.path.exists(photo_path): return
            print("[SHIFTWA] Memulai proses pengiriman log foto...")
            
            caption = (
                f"⚠️ *LOG KEAMANAN SMART HOME* ⚠️\n\n"
                f"👤 *Wajah terdeteksi:* {nama_user.upper()}\n"
                f"🚨 *Status Akses:* {status_akses}\n"
                f"⏰ *Waktu:* {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"--- AI Smart Home Security ---"
            )
            
            headers_auth = {
                "X-API-Key": SHIFTWA_API_KEY,
                "Content-Type": "application/json"
            }
            
            try:
                filename = os.path.basename(photo_path)
                file_size = os.path.getsize(photo_path)
                
                # Langkah 1: Minta URL upload tiket
                metadata = {"mime": "image/jpeg", "size": file_size, "filename": filename}
                res1 = requests.post(f"{SHIFTWA_BASE_URL}/messages/upload", headers=headers_auth, json=metadata, timeout=10)
                
                if res1.status_code not in (200, 201): return
                res1_data = res1.json()
                upload_url = res1_data.get("uploadUrl")
                storage_key = res1_data.get("storageKey")
                
                if not upload_url or not storage_key: return
                
                # Langkah 2: PUT byte gambar
                with open(photo_path, "rb") as raw_file:
                    res2 = requests.put(upload_url, headers={"Content-Type": "image/jpeg"}, data=raw_file, timeout=20)
                    
                if res2.status_code not in (200, 201, 204): return
                
                # Langkah 3: Kirim Media Message
                payload = {"to": WA_TARGET, "media": {"storageKey": storage_key, "caption": caption}}
                requests.post(f"{SHIFTWA_BASE_URL}/messages/send", headers=headers_auth, json=payload, timeout=10)
                print("[SHIFTWA] Log Keamanan Berhasil Dikirim!")
            except Exception as e:
                print(f"[SHIFTWA ERROR] Gagal kirim media: {e}")
                
        threading.Thread(target=target, daemon=True).start()

    def build_sistem_utama(self):
        self.clear_window()
        self.su_recognizer = None
        self.su_label_map = None
        self.su_processing = False 

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")
        tk.Button(top_bar, text="✖ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
        tk.Button(top_bar, text="Daftar Wajah", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT2, fg="white", relief="flat", padx=10, pady=4, command=self.build_daftar_wajah).pack(side="right", padx=0, pady=15)

        tk.Label(self, text="SISTEM UTAMA (SCANNING WAJAH)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 10))
        self.su_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.su_video_label.pack(pady=5)

        self.su_status_var = tk.StringVar(value="Memuat model matematika...")
        tk.Label(self, textvariable=self.su_status_var, font=("Segoe UI", 13), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center").pack(pady=15)

        self.su_recognizer, self.su_label_map = train_model()
        if self.su_recognizer is None:
            self.su_status_var.set("Dataset kosong. Daftarkan wajah Anda terlebih dahulu.")
            lcd_cetak("=== ERROR ===", "DATASET KOSONG", "Daftarkan Wajah!", "")
        else:
            self.su_status_var.set("Berdiri di depan kamera untuk mendeteksi wajah...")

        self.start_camera()
        self.update_su_camera()

    def update_su_camera(self):
        if self.cam is None: return
        
        # JEDA KEAMANAN 15 DETIK CONTROL LOGIC
        if self.cooldown_start_time is not None:
            sisa_jeda = 15.0 - (time.time() - self.cooldown_start_time)
            if sisa_jeda > 0:
                msg = f"Sistem Terkunci Keamanan! Mohon tunggu ({sisa_jeda:.1f}s)..."
                self.su_status_var.set(msg)
                lcd_cetak("=== JEDA AMAN ===", "SISTEM LOCK SPAM", f"Sisa: {int(sisa_jeda)} Detik", "Harap Menjauh")
                
                ret, frame = self.cam.read()
                if ret:
                    cv2.putText(frame, f"SISTEM LOCK ({sisa_jeda:.1f}s)", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                    self.render_frame(frame, self.su_video_label)
                self.camera_after_id = self.after(50, self.update_su_camera)
                return
            else:
                self.cooldown_start_time = None
                self.su_processing = False
                reset_semua_komponen_standby()

        ret, frame = self.cam.read()
        if ret:
            self.last_frame_bgr = frame.copy()
            display = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if not self.su_processing and len(faces) > 0:
                faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                wajah_utama = faces[0]
                (x, y, w, h) = wajah_utama
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
                self.su_processing = True
                threading.Thread(target=self.alur_keamanan_sekuensial, daemon=True).start()

            try: self.render_frame(display, self.su_video_label)
            except tk.TclError: return

        self.camera_after_id = self.after(50, self.update_su_camera)

    def alur_keamanan_sekuensial(self):
        bunyi_buzzer_sync(1)
        
        for i in range(3, 0, -1):
            self.su_set_status_threadsafe(f"Wajah terdeteksi! Mengunci posisi kamera dalam {i} detik...")
            lcd_cetak("WAJAH TERDETEKSI!", "Mohon Paskan Wajah", f"Proses Scan: {i} s", "Jangan Bergerak!")
            time.sleep(1.0)
            
        if self.su_recognizer is None or self.last_frame_bgr is None:
            self.su_processing = False
            return

        self.su_set_status_threadsafe("Memindai wajah...")
        lcd_cetak("=== SCANNING ===", "Mencocokkan Data", "Harap Tunggu...", "")
        
        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        if len(faces) == 0:
            bunyi_buzzer_sync(3)
            self.su_set_status_threadsafe("Pengecekan gagal: Wajah hilang dari kamera!")
            lcd_cetak("=== SCAN GAGAL ===", "Wajah Hilang!", "Mulai Cooldown...", "")
            self.cooldown_start_time = time.time()
            return

        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        (x, y, w, h) = faces[0]
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
        
        label, confidence = self.su_recognizer.predict(face_img)

        # Simpan capture log untuk lampiran ShiftWA
        cv2.imwrite("pintu_log.jpg", self.last_frame_bgr)

        if confidence < LBPH_THRESHOLD:
            nama_user = self.su_label_map.get(label)
            self.su_set_status_threadsafe(f"Wajah Teridentifikasi: {nama_user}.\nMenyiapkan Verifikasi Suara...")
            lcd_cetak("WAJAH TERDAFTAR", f"User: {nama_user}", "Membuka Mikrofon", "Bersiaplah...")
            
            bunyi_buzzer_sync(2)
            spoken_text = speech_to_text(status_callback=self.su_set_status_threadsafe)
            
            if spoken_text is None:
                bunyi_buzzer_sync(3)
                self.su_set_status_threadsafe("ANDA SALAH MEMASUKKAN PASSWORD (SUARA KOSONG)")
                lcd_cetak("=== AKSES DITOLAK ===", f"User: {nama_user}", "PASSWORD KOSONG!", "DISCHARGE AKTIF!")
                
                self.kirim_shiftwa_async(nama_user, "AKSES DITOLAK: PASSWORD SUARA KOSONG")
                _relay_set(RELAY_DISCHARGE_PIN, True)
                time.sleep(DURASI_DISCHARGE_DETIK) 
                _relay_set(RELAY_DISCHARGE_PIN, False)
            else:
                users = load_users()
                stored_hash = users.get(nama_user, {}).get("password")
                input_hash = hash_password(spoken_text)
                
                if stored_hash is not None and stored_hash == input_hash:
                    self.su_set_status_threadsafe(f'Suara: "{spoken_text}"\n\nSELAMAT, SILAHKAN MASUK!')
                    lcd_cetak("=== AKSES DITERIMA ===", f"Halo, {nama_user}", "SILAHKAN MASUK", "PINTU TERBUKA")
                    
                    bunyi_buzzer_sync(2)
                    self.kirim_shiftwa_async(nama_user, "AKSES DITERIMA (PINTU TERBUKA)")
                    
                    _relay_set(RELAY_SOLENOID_PIN, True)
                    time.sleep(DURASI_SOLENOID_DETIK)
                    _relay_set(RELAY_SOLENOID_PIN, False)
                else:
                    self.su_set_status_threadsafe(f'Suara: "{spoken_text}"\n\nANDA SALAH MEMASUKKAN PASSWORD')
                    lcd_cetak("=== AKSES DITOLAK ===", f"User: {nama_user}", "PASSWORD SALAH!", "DISCHARGE AKTIF!")
                    
                    bunyi_buzzer_sync(3) 
                    self.kirim_shiftwa_async(nama_user, f"AKSES DITOLAK: PASSWORD SALAH ('{spoken_text}')")
                    
                    _relay_set(RELAY_DISCHARGE_PIN, True)
                    time.sleep(DURASI_DISCHARGE_DETIK)
                    _relay_set(RELAY_DISCHARGE_PIN, False)
        else:
            self.su_set_status_threadsafe("ANDA BELUM TERDAFTAR (WAJAH ASING)")
            lcd_cetak("=== STRANGER ===", "WAJAH ASING!", "ANDA TIDAK DIKENAL", "AKSES DITOLAK")
            bunyi_buzzer_sync(3)
            self.kirim_shiftwa_async("Stranger / Orang Asing", "AKSES DITOLAK: WAJAH TIDAK DIKENAL")
            time.sleep(2)

        # Masuk mode jeda keamanan 15 detik setelah semua proses selesai
        self.cooldown_start_time = time.time()

    def su_set_status_threadsafe(self, msg):
        self.after(0, lambda: self.su_status_var.set(msg))

    # --- MENU KEDUA: REGISTRASI DATASET WAJAH BARU ---
    def build_daftar_wajah(self):
        self.clear_window()
        reset_semua_komponen_standby()
        lcd_cetak("MODE REGISTRASI", "Silahkan Isi Form", "Di Layar Aplikasi", "")

        self.dw_nama = None
        self.dw_user_dir = None
        self.dw_offset = 0
        self.dw_sample_count = 0

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")
        tk.Button(top_bar, text="✖ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
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
            
            # 1. Coba deteksi wajah lurus (Frontal) dulu
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            # 2. Jika wajah lurus tidak ketemu, cari wajah miring/samping (Profile)
            if len(faces) == 0:
                faces = profile_cascade.detectMultiScale(gray, 1.3, 5)
                # Jaga-jaga jika menghadap ke arah sebaliknya (karena profile cascade bawaan condong ke satu arah), 
                # kita flip gambarnya secara horizontal untuk mencari sudut sebaliknya.
                if len(faces) == 0:
                    flipped_gray = cv2.flip(gray, 1)
                    flipped_faces = profile_cascade.detectMultiScale(flipped_gray, 1.3, 5)
                    if len(flipped_faces) > 0:
                        # Kembalikan koordinat wajah yang di-flip ke koordinat asli
                        w_img = gray.shape[1]
                        faces = []
                        for (xf, yf, wf, hf) in flipped_faces:
                            faces.append([w_img - xf - wf, yf, wf, hf])
            
            # Jika salah satu ketemu (lurus/kiri/kanan), gambar kotak hijau di GUI
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
        lcd_cetak("MODE REGISTRASI", f"User: {nama}", "Ambil Foto Sampel", "Lewat Aplikasi")

    def dw_ambil_foto(self):
        if self.last_frame_bgr is None: return
        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        
        # Lakukan pencarian multi-angle yang sama saat tombol ditekan
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) == 0:
            faces = profile_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) == 0:
                flipped_gray = cv2.flip(gray, 1)
                flipped_faces = profile_cascade.detectMultiScale(flipped_gray, 1.3, 5)
                if len(flipped_faces) > 0:
                    w_img = gray.shape[1]
                    faces = [[w_img - flipped_faces[0][0] - flipped_faces[0][2], flipped_faces[0][1], flipped_faces[0][2], flipped_faces[0][3]]]

        if len(faces) == 0:
            self.dw_status_var.set("Wajah tidak terdeteksi oleh sensor kamera (Coba sesuaikan sudut)!")
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
        lcd_cetak("MODE REGISTRASI", f"User: {self.dw_nama}", f"Foto Ke-{self.dw_sample_count} Terambil", "Sukses!")

        if self.dw_sample_count >= MIN_SAMPLES:
            self.dw_btn_ambil.config(state="disabled")
            messagebox.showinfo("Sukses", f"Registrasi wajah '{self.dw_nama}' selesai!")
            self.build_sistem_utama()

if __name__ == "__main__":
    app = App()
    app.mainloop()
