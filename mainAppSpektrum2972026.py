"""
SISTEM KEAMANAN PINTU: WAJAH + SUARA (EDISI REVISI ALUR & SPEKTRUM MIC)
===================================================================
1. Buka Pintu dengan Wajah -> Terdeteksi -> Solenoid Aktif (Pintu Terbuka)
2. Jika Wajah Tidak Terdeteksi / Asing -> Verifikasi Password Suara (Mic)
   - Password Suara Benar -> Solenoid Aktif (Pintu Terbuka)
   - Password Suara Salah -> Electric Discharge 6s + Kirim Notifikasi WA
3. Pilihan ID Mic Dinamis + Auto-Detect Wireless Mic + Visualisator Spektrum
"""

import os
import json
import hashlib
import threading
import time
import serial
import random

import cv2
import numpy as np
import speech_recognition as sr

import tkinter as tk
from tkinter import ttk, messagebox

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

# --- INTEGRASI AUTOMATIC PATH CASCADE OPENCV ---
OPENCV_DATA_DIR = os.path.dirname(cv2.__file__) + "/data/"
CASCADE_PATH = os.path.join(OPENCV_DATA_DIR, "haarcascade_frontalface_default.xml")
PROFILE_CASCADE_PATH = os.path.join(OPENCV_DATA_DIR, "haarcascade_profileface.xml")

if not os.path.exists(CASCADE_PATH): CASCADE_PATH = "haarcascade_frontalface_default.xml"
if not os.path.exists(PROFILE_CASCADE_PATH): PROFILE_CASCADE_PATH = "haarcascade_profileface.xml"

face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
profile_cascade = cv2.CascadeClassifier(PROFILE_CASCADE_PATH)

# --- INTEGRASI PORT SERIAL UART DFPLAYER MINI ---
try:
    df_serial = serial.Serial("/dev/serial0", baudrate=9600, timeout=1)
    DFPLAYER_AVAILABLE = True
    print("[DFPLAYER] Modul Suara Serial Aktif.")
except Exception as e:
    DFPLAYER_AVAILABLE = False
    df_serial = None
    print(f"[DFPLAYER WARNING] Gagal terhubung ke modul suara: {e}")

def kirim_perintah_dfplayer(perintah, param1=0x00, param2=0x00):
    if not DFPLAYER_AVAILABLE or df_serial is None: 
        return
    versi, panjang, feedback = 0xFF, 0x06, 0x00
    jumlah = versi + panjang + perintah + feedback + param1 + param2
    checksum = 0xFFFF - jumlah + 1
    high_byte = (checksum >> 8) & 0xFF
    low_byte = checksum & 0xFF
    paket = bytes([0x7E, versi, panjang, perintah, feedback, param1, param2, high_byte, low_byte, 0xEF])
    
    try:
        df_serial.reset_input_buffer()
        df_serial.reset_output_buffer()
        df_serial.write(paket)
        df_serial.flush()
    except Exception as e:
        print(f"[DFPLAYER ERROR] Gagal kirim perintah: {e}")

def set_volume(volume):
    kirim_perintah_dfplayer(0x06, 0x00, volume)
    time.sleep(0.2)

def putar_lagu(nomor_track):
    kirim_perintah_dfplayer(0x12, 0x00, nomor_track)
    time.sleep(0.3)

# ============================================================
# KONFIGURASI SISTEM & PIN HARDWARE
# ============================================================

DATASET_DIR = "dataset" 
USERS_FILE = "users.json"
MIN_SAMPLES = 9 
FACE_SIZE = (200, 200) 
LBPH_THRESHOLD = 48 

VIDEO_DISPLAY_SIZE = (480, 270) 

COLOR_BG = "#1e1e2f"
COLOR_TEXT = "#f5f5f5"
COLOR_ACCENT = "#4c6ef5"
COLOR_ACCENT2 = "#12b886"
COLOR_DANGER = "#e03131"

ADMIN_USERNAME_DEFAULT = "admin"
ADMIN_PASSWORD_DEFAULT = "admin123"

SHIFTWA_API_KEY = "sk_live_50a3b10f8561a3615fd8e4db49094369b80855066da5a92066ad1102a15ac20c"
SHIFTWA_BASE_URL = "https://api.shiftwa.dev/v1"
WA_TARGET = "+6281267978173"

RELAY_SOLENOID_PIN = 27       # Relay 1 (Solenoid Pintu)
RELAY_DISCHARGE_PIN = 23      # Relay 2 (Electric Discharge)
BUZZER_PIN = 22               
LED_TERDETEKSI_PIN = 24      
LED_SALAH_PIN = 25            

DURASI_SOLENOID_DETIK = 4
DURASI_DISCHARGE_DETIK = 6    

RELAY_ACTIVE_LOW = True
BUZZER_ACTIVE_LOW = False

# ============================================================
# UTILITAS HARDWARE, LCD, & MIKROFON
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

# Deteksi Otomatis & Pilihan Mikrofon
def dapatkan_daftar_mic():
    mic_list = []
    try:
        names = sr.Microphone.list_microphone_names()
        for i, name in enumerate(names):
            mic_list.append((i, name))
    except Exception as e:
        print(f"[MIC ERROR] Gagal mendeteksi mikrofon: {e}")
    return mic_list

def dapatkan_index_mic_otomatis():
    mics = dapatkan_daftar_mic()
    # Kata kunci untuk memprioritaskan mic wireless / USB audio dan mengabaikan keyboard
    keywords = ["wireless", "usb audio", "pnp", "microphone", "headset", "audio"]
    for idx, name in mics:
        name_lower = name.lower()
        if "keyboard" in name_lower:
            continue
        for kw in keywords:
            if kw in name_lower:
                return idx
    return 2 if len(mics) > 2 else (0 if len(mics) > 0 else None)

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

def speech_to_text(device_id=None, status_callback=None, wave_callback=None):
    def update(msg, l1="", l2="", l3="", l4=""):
        if status_callback: status_callback(msg)
        lcd_cetak(l1, l2, l3, l4)
        
    recognizer_sr = sr.Recognizer()
    id_mic = device_id if device_id is not None else dapatkan_index_mic_otomatis()
    sample_rate = 48000
    
    # Visualisasi Spektrum Suara Aktif
    animating = True
    def animate_spectrum():
        while animating:
            if wave_callback:
                # Membuat bar spektrum audio acak untuk efek visualisator
                heights = [random.randint(5, 45) for _ in range(16)]
                wave_callback(heights)
            time.sleep(0.08)

    t_anim = threading.Thread(target=animate_spectrum, daemon=True)
    t_anim.start()

    try:
        with sr.Microphone(device_index=id_mic, sample_rate=sample_rate) as source:
            update("Menyesuaikan ambang batas kebisingan...", "VERIFIKASI SUARA", "Mohon Tenang...", "Kalibrasi Mic...", "")
            recognizer_sr.adjust_for_ambient_noise(source, duration=0.8)
            
            update("Silahkan ucapkan password anda...", "VERIFIKASI SUARA", "Silahkan Ucapkan", "Password Anda!", "")
            audio = recognizer_sr.listen(source, timeout=5, phrase_time_limit=5)
    except Exception as e:
        print(f"[AUDIO ERROR]: {e}")
        animating = False
        if wave_callback: wave_callback([0]*16)
        return None
    
    animating = False
    if wave_callback: wave_callback([0]*16)

    update("Mengirim audio ke Cloud Google STT...", "VERIFIKASI SUARA", "Memproses Audio...", "Harap Tunggu...", "")
    try:
        res = recognizer_sr.recognize_google(audio, language="id-ID")
        return res
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
        self.title("Sistem Keamanan Pintu: Wajah + Suara")
        self.geometry("800x720")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        pastikan_folder_dataset()
        self.cam = None
        self.camera_after_id = None
        self.last_frame_bgr = None
        self.cooldown_start_time = None 
        
        self.selected_mic_id = dapatkan_index_mic_otomatis()
        
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

    def kirim_shiftwa_async(self, nama_user, status_akses, photo_path="pintu_log.jpg"):
        def target():
            if requests is None or not os.path.exists(photo_path): return
            print("[SHIFTWA] Memulai pengiriman log peringatan ke WhatsApp...")
            
            caption = (
                f"⚠️ *PERINGATAN KEAMANAN SMART HOME* ⚠️\n\n"
                f"👤 *Wajah terdeteksi:* {nama_user.upper()}\n"
                f"🚨 *Status Akses:* {status_akses}\n"
                f"⏰ *Waktu:* {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"⚡ *Tindakan:* Electric Discharge Aktif 6 Detik!\n"
                f"--- AI Smart Home Security ---"
            )
            
            headers_auth = {
                "X-API-Key": SHIFTWA_API_KEY,
                "Content-Type": "application/json"
            }
            
            try:
                filename = os.path.basename(photo_path)
                file_size = os.path.getsize(photo_path)
                
                metadata = {"mime": "image/jpeg", "size": file_size, "filename": filename}
                res1 = requests.post(f"{SHIFTWA_BASE_URL}/messages/upload", headers=headers_auth, json=metadata, timeout=10)
                
                if res1.status_code not in (200, 201): return
                res1_data = res1.json()
                upload_url = res1_data.get("uploadUrl")
                storage_key = res1_data.get("storageKey")
                
                if not upload_url or not storage_key: return
                
                with open(photo_path, "rb") as raw_file:
                    res2 = requests.put(upload_url, headers={"Content-Type": "image/jpeg"}, data=raw_file, timeout=20)
                    
                if res2.status_code not in (200, 201, 204): return
                
                payload = {"to": WA_TARGET, "media": {"storageKey": storage_key, "caption": caption}}
                requests.post(f"{SHIFTWA_BASE_URL}/messages/send", headers=headers_auth, json=payload, timeout=10)
                print("[SHIFTWA] Log Keamanan Berhasil Dikirim ke WA!")
            except Exception as e:
                print(f"[SHIFTWA ERROR] Gagal kirim media: {e}")
                
        threading.Thread(target=target, daemon=True).start()

    # ============================================================
    # 1. HALAMAN UTAMA (REVISI ALUR & INTEGRASI MIC + SPEKTRUM)
    # ============================================================
    def build_sistem_utama(self):
        self.clear_window()
        self.su_recognizer = None
        self.su_label_map = None
        self.su_processing = False 

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")
        tk.Button(top_bar, text="✖ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
        tk.Button(top_bar, text="Daftar Wajah", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT2, fg="white", relief="flat", padx=10, pady=4, command=self.build_login_admin).pack(side="right", padx=0, pady=15)

        # Dropdown Pemilihan Mic di Top Bar
        mic_frame = tk.Frame(top_bar, bg=COLOR_BG)
        mic_frame.pack(side="left", padx=15, pady=10)
        tk.Label(mic_frame, text="Pilih Mic:", font=("Segoe UI", 9, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(side="left", padx=(0,5))
        
        mics = dapatkan_daftar_mic()
        mic_options = [f"[{m[0]}] {m[1][:25]}" for m in mics] if mics else ["Mic Tidak Ditemukan"]
        self.selected_mic_var = tk.StringVar(value=mic_options[0] if mic_options else "")
        
        # Temukan opsi default mic otomatis
        auto_mic_idx = dapatkan_index_mic_otomatis()
        for opt in mic_options:
            if opt.startswith(f"[{auto_mic_idx}]"):
                self.selected_mic_var.set(opt)
                break
                
        mic_dropdown = ttk.OptionMenu(mic_frame, self.selected_mic_var, self.selected_mic_var.get(), *mic_options, command=self.on_mic_change)
        mic_dropdown.pack(side="left")

        tk.Label(self, text="SISTEM UTAMA KEAMANAN PINTU", font=("Segoe UI", 15, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 5))
        
        self.su_video_label = tk.Label(self, bg="black", width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.su_video_label.pack(pady=5)

        # Visualisator Spektrum Suara (Canvas Waveform)
        self.spectrum_canvas = tk.Canvas(self, width=320, height=50, bg="#11111d", highlightthickness=0)
        self.spectrum_canvas.pack(pady=5)
        self.draw_spectrum([0]*16)

        self.su_status_var = tk.StringVar(value="Memuat model matematika...")
        tk.Label(self, textvariable=self.su_status_var, font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT, wraplength=720, justify="center").pack(pady=10)

        self.su_recognizer, self.su_label_map = train_model()
        if self.su_recognizer is None:
            self.su_status_var.set("Dataset kosong. Daftarkan wajah Anda terlebih dahulu.")
            lcd_cetak("=== ERROR ===", "DATASET KOSONG", "Daftarkan Wajah!", "")
        else:
            self.su_status_var.set("Berdiri di depan kamera untuk verifikasi wajah...")
            reset_semua_komponen_standby()

        self.start_camera()
        self.update_su_camera()

    def on_mic_change(self, val):
        try:
            mic_id = int(val.split("]")[0].replace("[", ""))
            self.selected_mic_id = mic_id
            print(f"[MIC SELECT] Microphone diubah ke ID: {mic_id}")
        except Exception as e:
            print(f"[MIC ERROR] Gagal mengubah ID mic: {e}")

    def draw_spectrum(self, heights):
        if not hasattr(self, 'spectrum_canvas') or not self.spectrum_canvas.winfo_exists():
            return
        self.spectrum_canvas.delete("all")
        width = 320
        num_bars = len(heights)
        bar_width = (width - (num_bars * 4)) / num_bars
        
        for i, h in enumerate(heights):
            x0 = i * (bar_width + 4) + 10
            y0 = 50 - h
            x1 = x0 + bar_width
            y1 = 50
            self.spectrum_canvas.create_rectangle(x0, y0, x1, y1, fill="#12b886", outline="")

    def update_spectrum_threadsafe(self, heights):
        self.after(0, lambda: self.draw_spectrum(heights))

    def update_su_camera(self):
        if self.cam is None: return
        
        if self.cooldown_start_time is not None:
            sisa_jeda = 7.0 - (time.time() - self.cooldown_start_time)
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
            if len(faces) == 0:
                faces = profile_cascade.detectMultiScale(gray, 1.3, 5)
                if len(faces) == 0:
                    flipped_gray = cv2.flip(gray, 1)
                    flipped_faces = profile_cascade.detectMultiScale(flipped_gray, 1.3, 5)
                    if len(flipped_faces) > 0:
                        w_img = gray.shape[1]
                        faces = []
                        for (xf, yf, wf, hf) in flipped_faces:
                            faces.append([w_img - xf - wf, yf, wf, hf])
            
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

    # ============================================================
    # ALUR SISTEM UTAMA BARU (WAJAH -> SOLENOID; JIKA GAGAL -> SUARA)
    # ============================================================
    def alur_keamanan_sekuensial(self):
        set_volume(25)
        bunyi_buzzer_sync(1)
        
        # Track 2: Wajah Anda Terdeteksi
        putar_lagu(2)
        time.sleep(1.5) 
        
        for i in range(3, 0, -1):
            self.su_set_status_threadsafe(f"Wajah terdeteksi! Memindai dalam {i} detik...")
            lcd_cetak("WAJAH TERDETEKSI!", "Mohon Paskan Wajah", f"Proses Scan: {i} s", "Jangan Bergerak!")
            time.sleep(1.0)
            
        if self.su_recognizer is None or self.last_frame_bgr is None:
            self.su_processing = False
            return

        self.su_set_status_threadsafe("Memindai dan mencocokkan wajah...")
        lcd_cetak("=== SCANNING ===", "Mencocokkan Data", "Harap Tunggu...", "")
        
        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) == 0:
            faces = profile_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) == 0:
                flipped_gray = cv2.flip(gray, 1)
                flipped_faces = profile_cascade.detectMultiScale(flipped_gray, 1.3, 5)
                if len(flipped_faces) > 0:
                    w_img = gray.shape[1]
                    faces = [[w_img - flipped_faces[0][0] - flipped_faces[0][2], flipped_faces[0][1], flipped_faces[0][2], flipped_faces[0][3]]]
        
        wajah_terverifikasi = False
        nama_user = "Orang Asing"

        if len(faces) > 0:
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            (x, y, w, h) = faces[0]
            face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
            
            label, confidence = self.su_recognizer.predict(face_img)
            cv2.imwrite("pintu_log.jpg", self.last_frame_bgr)

            if confidence < LBPH_THRESHOLD:
                wajah_terverifikasi = True
                nama_user = self.su_label_map.get(label, "User")

        # -----------------------------------------------------------------
        # TAHAP 1: JIKA WAJAH TERDETEKSI & TERDAFTAR -> BUKA PINTU LANGSUNG!
        # -----------------------------------------------------------------
        if wajah_terverifikasi:
            self.su_set_status_threadsafe(f"WAJAH TERDETEKSI: Welcome {nama_user}!\nSELAMAT, SILAHKAN MASUK!")
            lcd_cetak("=== AKSES DITERIMA ===", f"Halo, {nama_user}", "SILAHKAN MASUK", "PINTU TERBUKA")
            
            # Track 1: Selamat Datang & Track 7: Terimakasih Silahkan Masuk
            putar_lagu(1)
            time.sleep(1.8)
            putar_lagu(7)
            time.sleep(2.0)
            
            bunyi_buzzer_sync(2)
            _relay_set(RELAY_SOLENOID_PIN, True)
            time.sleep(DURASI_SOLENOID_DETIK)
            _relay_set(RELAY_SOLENOID_PIN, False)
            
            self.cooldown_start_time = time.time()
            return

        # -----------------------------------------------------------------
        # TAHAP 2: JIKA WAJAH GAGAL / ASING -> AKTIFKAN FALLBACK VERIFIKASI SUARA
        # -----------------------------------------------------------------
        bunyi_buzzer_sync(2)
        # Track 3: Wajah Anda Tidak Terdeteksi / Asing
        putar_lagu(3)
        time.sleep(1.5)
        # Track 4: Silahkan Ucapkan Password Anda
        putar_lagu(4)
        time.sleep(2.0)
        
        self.su_set_status_threadsafe("Wajah tidak dikenal / tidak terdeteksi!\nMembuka mikrofon, silahkan ucapkan password suara...")
        lcd_cetak("WAJAH TIDAK DIKENAL", "Gunakan Password", "Silahkan Ucapkan", "Password Suara!")
        
        spoken_text = speech_to_text(
            device_id=self.selected_mic_id,
            status_callback=self.su_set_status_threadsafe,
            wave_callback=self.update_spectrum_threadsafe
        )
        
        password_benar = False
        users = load_users()

        if spoken_text is not None:
            input_hash = hash_password(spoken_text)
            # Pengecekan kata kunci ke semua user terdaftar
            for u_name, u_data in users.items():
                if u_data.get("password") == input_hash:
                    password_benar = True
                    nama_user = u_name
                    break

        if password_benar:
            # PASSWORD SUARA BENAR -> BUKA PINTU
            putar_lagu(5) # Track 5: Password Anda Benar
            time.sleep(1.8)
            putar_lagu(7) # Track 7: Terimakasih Silahkan Masuk
            time.sleep(2.0)
            
            self.su_set_status_threadsafe(f'Suara: "{spoken_text}"\nPASSWORD BENAR (User: {nama_user})! SILAHKAN MASUK!')
            lcd_cetak("=== AKSES DITERIMA ===", f"User: {nama_user}", "PASSWORD BENAR", "PINTU TERBUKA")
            
            bunyi_buzzer_sync(2)
            _relay_set(RELAY_SOLENOID_PIN, True)
            time.sleep(DURASI_SOLENOID_DETIK)
            _relay_set(RELAY_SOLENOID_PIN, False)

        else:
            # PASSWORD SUARA SALAH / GAGAL -> ELECTRIC DISCHARGE + WHATSAPP NOTIF
            bunyi_buzzer_sync(3)
            putar_lagu(6) # Track 6: Password Anda Salah
            time.sleep(1.8)
            
            teks_log = spoken_text if spoken_text else "Suara Tidak Terdeteksi / Kosong"
            self.su_set_status_threadsafe(f'Suara: "{teks_log}"\nPASSWORD SALAH! ELECTRIC DISCHARGE AKTIF (6s)!')
            lcd_cetak("=== AKSES DITOLAK ===", "PASSWORD SALAH!", "DISCHARGE AKTIF!", "KIRIM NOTIF WA...")
            
            # SIMPAN FOTO FAILED LOG & KIRIM WA (ShiftWA)
            cv2.imwrite("pintu_log.jpg", self.last_frame_bgr)
            self.kirim_shiftwa_async(nama_user, f"AKSES DITOLAK (Password Salah: '{teks_log}')")
            
            # AKTIFKAN ELECTRIC DISCHARGE 6 DETIK
            _relay_set(RELAY_DISCHARGE_PIN, True)
            time.sleep(DURASI_DISCHARGE_DETIK)
            _relay_set(RELAY_DISCHARGE_PIN, False)

        self.cooldown_start_time = time.time()

    def su_set_status_threadsafe(self, msg):
        self.after(0, lambda: self.su_status_var.set(msg))

    # ============================================================
    # 2. HALAMAN LOGIN ADMIN (VERIFIKASI)
    # ============================================================
    def build_login_admin(self):
        self.clear_window()
        reset_semua_komponen_standby()
        lcd_cetak("MODE ADMINISTRATOR", "Masukan Akun Admin", "Untuk Akses Reg.", "")

        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")
        tk.Button(top_bar, text="✖ Keluar", font=("Segoe UI", 10, "bold"), bg=COLOR_DANGER, fg="white", relief="flat", padx=10, pady=4, command=self.on_close).pack(side="right", padx=15, pady=15)
        tk.Button(top_bar, text="Sistem Utama", font=("Segoe UI", 10, "bold"), bg=COLOR_ACCENT, fg="white", relief="flat", padx=10, pady=4, command=self.build_sistem_utama).pack(side="right", padx=0, pady=15)

        tk.Label(self, text="LOGIN ADMINISTRATOR", font=("Segoe UI", 18, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(40, 20))

        login_box = tk.Frame(self, bg=COLOR_BG)
        login_box.pack(pady=20)

        tk.Label(login_box, text="Username:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=10, pady=10)
        self.login_entry_user = tk.Entry(login_box, font=("Segoe UI", 12), width=22)
        self.login_entry_user.grid(row=0, column=1, padx=10, pady=10)
        self.login_entry_user.focus_set()

        tk.Label(login_box, text="Password:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=10, pady=10)
        self.login_entry_pass = tk.Entry(login_box, font=("Segoe UI", 12), width=22, show="*")
        self.login_entry_pass.grid(row=1, column=1, padx=10, pady=10)

        self.login_status_var = tk.StringVar(value="Silahkan masukkan Username & Password Admin.")
        tk.Label(self, textvariable=self.login_status_var, font=("Segoe UI", 11), bg=COLOR_BG, fg="#ff6b6b").pack(pady=10)

        tk.Button(self, text="MASUK LOGIN", font=("Segoe UI", 12, "bold"), bg=COLOR_ACCENT2, fg="white", relief="flat", width=18, pady=6, command=self.proses_login_admin).pack(pady=15)

    def proses_login_admin(self):
        user = self.login_entry_user.get().strip()
        pwd = self.login_entry_pass.get().strip()

        if user == ADMIN_USERNAME_DEFAULT and pwd == ADMIN_PASSWORD_DEFAULT:
            bunyi_buzzer_sync(2)
            messagebox.showinfo("Login Berhasil", "Akses Admin Diterima! Silahkan Daftarkan Wajah Baru.")
            self.build_daftar_wajah()
        else:
            bunyi_buzzer_sync(3)
            self.login_status_var.set("Username atau Password Salah! Akses Ditolak.")
            lcd_cetak("LOGIN ADMIN GAGAL", "Username / Password", "Salah!", "Coba Lagi...")

    # ============================================================
    # 3. HALAMAN REGISTRASI DATASET WAJAH BARU
    # ============================================================
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

        tk.Label(self, text="REGISTRASI USER BARU (ADMIN MODE)", font=("Segoe UI", 16, "bold"), bg=COLOR_BG, fg=COLOR_TEXT).pack(pady=(0, 10))

        form_frame = tk.Frame(self, bg=COLOR_BG)
        form_frame.pack(pady=5)
        tk.Label(form_frame, text="Nama:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_nama = tk.Entry(form_frame, font=("Segoe UI", 12), width=22)
        self.dw_entry_nama.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form_frame, text="Password Suara:", font=("Segoe UI", 12), bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=5, pady=5)
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
            if len(faces) == 0:
                faces = profile_cascade.detectMultiScale(gray, 1.3, 5)
                if len(faces) == 0:
                    flipped_gray = cv2.flip(gray, 1)
                    flipped_faces = profile_cascade.detectMultiScale(flipped_gray, 1.3, 5)
                    if len(flipped_faces) > 0:
                        w_img = gray.shape[1]
                        faces = []
                        for (xf, yf, wf, hf) in flipped_faces:
                            faces.append([w_img - xf - wf, yf, wf, hf])
            
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
        
        msg = f"Wajah siap dipindai. Kumpulkan {MIN_SAMPLES} sampel (Lurus, Kiri, Kanan)."
        self.dw_status_var.set(msg)
        lcd_cetak("MODE REGISTRASI", f"User: {nama}", "Ambil Foto Sampel", "Lewat Aplikasi")

    def dw_ambil_foto(self):
        if self.last_frame_bgr is None: return
        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        
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
        
        if self.dw_sample_count <= 3:
            dw_msg = f"Sampel {self.dw_sample_count}/9 disimpan. Tetap posisi LURUS."
        elif self.dw_sample_count <= 6:
            dw_msg = f"Sampel {self.dw_sample_count}/9 disimpan. Sekarang menolehlah ke KIRI."
        else:
            dw_msg = f"Sampel {self.dw_sample_count}/9 disimpan. Sekarang menolehlah ke KANAN."
            
        self.dw_status_var.set(dw_msg)
        lcd_cetak("MODE REGISTRASI", f"User: {self.dw_nama}", f"Foto Ke-{self.dw_sample_count} Terambil", "Sukses!")

        if self.dw_sample_count >= MIN_SAMPLES:
            self.dw_btn_ambil.config(state="disabled")
            messagebox.showinfo("Sukses", f"Registrasi wajah '{self.dw_nama}' selesai!")
            self.build_sistem_utama()

if __name__ == "__main__":
    app = App()
    bunyi_buzzer_sync(3)
    app.mainloop()
