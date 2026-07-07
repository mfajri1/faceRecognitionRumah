# -*- coding: utf-8 -*-
"""
SISTEM DETEKSI WAJAH + PASSWORD SUARA (VERSI GUI)
====================================================

Tampilan GUI menggunakan Tkinter, dengan 2 menu utama (tombol):

1. Sistem Utama
   - Kamera tampil langsung di jendela.
   - Klik "Verifikasi Wajah" -> sistem cek apakah wajah terdaftar.
   - Jika TIDAK terdaftar -> tampil "ANDA BELUM TERDAFTAR".
   - Jika terdaftar -> sistem otomatis merekam suara lewat microphone untuk
     password (speech-to-text):
       - Salah  -> "ANDA SALAH MEMASUKKAN PASSWORD"
       - Benar  -> "SELAMAT, SILAHKAN MASUK"

2. Daftar Wajah Baru
   - Isi Nama + Password (diketik, bukan suara, karena ini dipakai sebagai
     "kunci" yang nanti dicocokkan dengan ucapan saat verifikasi).
   - Ambil minimal 3 foto sample wajah lewat kamera.
   - Struktur folder dataset: dataset/<nama_user>/<foto-foto>.jpg

Kebutuhan library (lihat requirements.txt):
    pip install opencv-contrib-python SpeechRecognition PyAudio numpy Pillow

Catatan instalasi PyAudio di Windows (jika "pip install pyaudio" gagal):
    pip install pipwin
    pipwin install pyaudio
"""

import os
import json
import hashlib
import threading

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

# ============================================================
# KONFIGURASI / KONSTANTA
# ============================================================

DATASET_DIR = "dataset"            # dataset/<nama_user>/foto.jpg
USERS_FILE = "users.json"          # menyimpan hash password tiap user
MIN_SAMPLES = 3                    # minimal sample wajah per user
FACE_SIZE = (200, 200)             # ukuran standar wajah setelah di-crop
LBPH_THRESHOLD = 70                # ambang confidence LBPH (makin kecil = makin yakin cocok)
VIDEO_DISPLAY_SIZE = (640, 360)    # ukuran tampilan video di GUI

COLOR_BG = "#1e1e2f"
COLOR_TEXT = "#f5f5f5"
COLOR_ACCENT = "#4c6ef5"
COLOR_ACCENT2 = "#12b886"
COLOR_DANGER = "#555555"

# Haar Cascade untuk deteksi wajah (bawaan OpenCV)
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(CASCADE_PATH)


# ============================================================
# UTILITAS UMUM (sama seperti versi console)
# ============================================================

def pastikan_folder_dataset():
    os.makedirs(DATASET_DIR, exist_ok=True)


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def hash_password(teks):
    """Normalisasi teks (huruf kecil, hapus spasi) lalu hash dengan SHA-256."""
    normalisasi = teks.strip().lower().replace(" ", "")
    return hashlib.sha256(normalisasi.encode("utf-8")).hexdigest()


def train_model():
    """Membaca semua foto di folder dataset, lalu melatih model LBPH."""
    if not os.path.exists(DATASET_DIR):
        return None, None

    faces = []
    labels = []
    label_map = {}
    current_label = 0

    for nama_user in sorted(os.listdir(DATASET_DIR)):
        user_path = os.path.join(DATASET_DIR, nama_user)
        if not os.path.isdir(user_path):
            continue

        file_foto = [
            f for f in os.listdir(user_path)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if not file_foto:
            continue

        label_map[current_label] = nama_user
        for nama_file in file_foto:
            path_foto = os.path.join(user_path, nama_file)
            img = cv2.imread(path_foto, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            img = cv2.resize(img, FACE_SIZE)
            faces.append(img)
            labels.append(current_label)

        current_label += 1

    if len(faces) == 0:
        return None, None

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(faces, np.array(labels))
    return recognizer, label_map


def speech_to_text(status_callback=None):
    """Merekam suara dari microphone -> teks (Google STT, bahasa Indonesia).
    status_callback(msg) dipanggil untuk memberi update ke GUI (opsional)."""

    def update(msg):
        if status_callback:
            status_callback(msg)

    recognizer_sr = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            update("Menyesuaikan suara latar belakang...")
            recognizer_sr.adjust_for_ambient_noise(source, duration=1)
            update("Silahkan ucapkan password anda sekarang...")
            audio = recognizer_sr.listen(source, timeout=6, phrase_time_limit=6)
    except sr.WaitTimeoutError:
        update("Tidak ada suara terdeteksi (timeout).")
        return None
    except OSError as e:
        update(f"Microphone tidak ditemukan / tidak bisa diakses: {e}")
        return None

    update("Memproses suara...")
    try:
        teks = recognizer_sr.recognize_google(audio, language="id-ID")
        return teks
    except sr.UnknownValueError:
        update("Suara tidak dapat dikenali, mohon ucapkan lebih jelas.")
        return None
    except sr.RequestError as e:
        update(f"Gagal terhubung ke layanan speech recognition: {e}")
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

        self.build_home()

    # ------------------------------------------------------------------
    # HELPER UMUM
    # ------------------------------------------------------------------
    def clear_window(self):
        if self.camera_after_id is not None:
            self.after_cancel(self.camera_after_id)
            self.camera_after_id = None
        self.release_camera()
        for widget in self.winfo_children():
            widget.destroy()

    def start_camera(self):
        if self.cam is None:
            self.cam = cv2.VideoCapture(0)

    def release_camera(self):
        if self.cam is not None:
            self.cam.release()
            self.cam = None

    def render_frame(self, frame_bgr, label_widget):
        if not label_widget.winfo_exists():
            return
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb = cv2.resize(frame_rgb, VIDEO_DISPLAY_SIZE)
        img = Image.fromarray(frame_rgb)
        imgtk = ImageTk.PhotoImage(image=img)
        label_widget.imgtk = imgtk  # simpan referensi agar tidak di-garbage-collect
        label_widget.configure(image=imgtk)

    def on_close(self):
        self.release_camera()
        self.destroy()

    # ------------------------------------------------------------------
    # HALAMAN: HOME (MENU UTAMA)
    # ------------------------------------------------------------------
    def build_home(self):
        self.clear_window()

        # --- Bar atas: tombol Keluar di pojok kanan atas ---
        top_bar = tk.Frame(self, bg=COLOR_BG)
        top_bar.pack(fill="x", side="top")

        tk.Button(
            top_bar, text="✕ Keluar", font=("Segoe UI", 10, "bold"),
            bg=COLOR_DANGER, fg="white", relief="flat",
            padx=10, pady=4, command=self.on_close
        ).pack(side="right", padx=15, pady=15)

        # --- Konten tengah ---
        center_frame = tk.Frame(self, bg=COLOR_BG)
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            center_frame, text="SISTEM DETEKSI WAJAH\n+ PASSWORD SUARA",
            font=("Segoe UI", 22, "bold"), bg=COLOR_BG, fg=COLOR_TEXT, justify="center"
        ).pack(pady=(0, 50))

        tk.Button(
            center_frame, text="Sistem Utama", font=("Segoe UI", 14), width=24, height=2,
            bg=COLOR_ACCENT, fg="white", relief="flat", command=self.build_sistem_utama
        ).pack(pady=15)

        tk.Button(
            center_frame, text="Daftar Wajah Baru", font=("Segoe UI", 14), width=24, height=2,
            bg=COLOR_ACCENT2, fg="white", relief="flat", command=self.build_daftar_wajah
        ).pack(pady=15)

    # ------------------------------------------------------------------
    # HALAMAN: SISTEM UTAMA
    # ------------------------------------------------------------------
    def build_sistem_utama(self):
        self.clear_window()

        self.su_recognizer = None
        self.su_label_map = None
        self.su_nama_terdeteksi = None

        tk.Label(
            self, text="SISTEM UTAMA", font=("Segoe UI", 18, "bold"),
            bg=COLOR_BG, fg=COLOR_TEXT
        ).pack(pady=15)

        self.su_video_label = tk.Label(self, bg="black",
                                        width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.su_video_label.pack(pady=10)

        self.su_status_var = tk.StringVar(value="Mempersiapkan kamera & model wajah...")
        tk.Label(
            self, textvariable=self.su_status_var, font=("Segoe UI", 13),
            bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center"
        ).pack(pady=15)

        btn_frame = tk.Frame(self, bg=COLOR_BG)
        btn_frame.pack(pady=10)

        self.su_btn_verify = tk.Button(
            btn_frame, text="Verifikasi Wajah", font=("Segoe UI", 12),
            bg=COLOR_ACCENT, fg="white", relief="flat", width=20,
            command=self.su_verify_face
        )
        self.su_btn_verify.grid(row=0, column=0, padx=10)

        tk.Button(
            btn_frame, text="Kembali ke Menu", font=("Segoe UI", 12),
            bg=COLOR_DANGER, fg="white", relief="flat", width=18,
            command=self.build_home
        ).grid(row=0, column=1, padx=10)

        self.su_recognizer, self.su_label_map = train_model()
        if self.su_recognizer is None:
            self.su_status_var.set(
                "Dataset wajah masih kosong.\nSilahkan daftar wajah dahulu lewat menu 'Daftar Wajah Baru'."
            )
            self.su_btn_verify.config(state="disabled")
        else:
            self.su_status_var.set("Arahkan wajah ke kamera, lalu klik 'Verifikasi Wajah'.")

        self.start_camera()
        self.update_su_camera()

    def update_su_camera(self):
        if self.cam is None:
            return
        ret, frame = self.cam.read()
        if ret:
            self.last_frame_bgr = frame.copy()
            display = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            for (x, y, w, h) in faces:
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
            try:
                self.render_frame(display, self.su_video_label)
            except tk.TclError:
                return
        self.camera_after_id = self.after(20, self.update_su_camera)

    def su_verify_face(self):
        if self.last_frame_bgr is None:
            return

        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            self.su_status_var.set("Wajah tidak terdeteksi, posisikan wajah di depan kamera.")
            return

        (x, y, w, h) = faces[0]
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)
        label, confidence = self.su_recognizer.predict(face_img)

        if confidence < LBPH_THRESHOLD:
            nama_user = self.su_label_map.get(label)
            self.su_nama_terdeteksi = nama_user
            self.su_status_var.set(
                f"Wajah dikenali sebagai '{nama_user}'.\nSilahkan ucapkan password anda..."
            )
            self.su_btn_verify.config(state="disabled")
            threading.Thread(target=self.su_proses_password, daemon=True).start()
        else:
            self.su_status_var.set("ANDA BELUM TERDAFTAR")

    def su_proses_password(self):
        spoken_text = speech_to_text(status_callback=self.su_set_status_threadsafe)

        if spoken_text is None:
            self.su_set_status_threadsafe(
                "Password tidak dikenali lewat suara.\nKlik 'Verifikasi Wajah' untuk coba lagi."
            )
            self.su_enable_verify_threadsafe()
            return

        users = load_users()
        nama_user = self.su_nama_terdeteksi
        stored_hash = users.get(nama_user, {}).get("password")
        input_hash = hash_password(spoken_text)

        if stored_hash is not None and stored_hash == input_hash:
            self.su_set_status_threadsafe(f'Suara terdengar: "{spoken_text}"\n\nSELAMAT, SILAHKAN MASUK')
        else:
            self.su_set_status_threadsafe(f'Suara terdengar: "{spoken_text}"\n\nANDA SALAH MEMASUKKAN PASSWORD')

        self.su_enable_verify_threadsafe()

    def su_set_status_threadsafe(self, msg):
        self.after(0, lambda: self.su_status_var.set(msg))

    def su_enable_verify_threadsafe(self):
        self.after(0, lambda: self.su_btn_verify.config(state="normal"))

    # ------------------------------------------------------------------
    # HALAMAN: DAFTAR WAJAH BARU
    # ------------------------------------------------------------------
    def build_daftar_wajah(self):
        self.clear_window()

        self.dw_nama = None
        self.dw_user_dir = None
        self.dw_offset = 0
        self.dw_sample_count = 0

        tk.Label(
            self, text="DAFTAR WAJAH BARU", font=("Segoe UI", 18, "bold"),
            bg=COLOR_BG, fg=COLOR_TEXT
        ).pack(pady=15)

        form_frame = tk.Frame(self, bg=COLOR_BG)
        form_frame.pack(pady=5)

        tk.Label(form_frame, text="Nama:", font=("Segoe UI", 12),
                 bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_nama = tk.Entry(form_frame, font=("Segoe UI", 12), width=22)
        self.dw_entry_nama.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form_frame, text="Password:", font=("Segoe UI", 12),
                 bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.dw_entry_password = tk.Entry(form_frame, font=("Segoe UI", 12), width=22, show="*")
        self.dw_entry_password.grid(row=1, column=1, padx=5, pady=5)

        self.dw_btn_mulai = tk.Button(
            form_frame, text="Mulai Pendaftaran", font=("Segoe UI", 11),
            bg=COLOR_ACCENT, fg="white", relief="flat", command=self.dw_mulai
        )
        self.dw_btn_mulai.grid(row=0, column=2, rowspan=2, padx=15)

        self.dw_video_label = tk.Label(self, bg="black",
                                        width=VIDEO_DISPLAY_SIZE[0], height=VIDEO_DISPLAY_SIZE[1])
        self.dw_video_label.pack(pady=10)

        self.dw_status_var = tk.StringVar(value="Isi nama & password, lalu klik 'Mulai Pendaftaran'.")
        tk.Label(
            self, textvariable=self.dw_status_var, font=("Segoe UI", 12),
            bg=COLOR_BG, fg=COLOR_TEXT, wraplength=700, justify="center"
        ).pack(pady=10)

        btn_frame = tk.Frame(self, bg=COLOR_BG)
        btn_frame.pack(pady=10)

        self.dw_btn_ambil = tk.Button(
            btn_frame, text=f"Ambil Foto Sample (0/{MIN_SAMPLES})", font=("Segoe UI", 12),
            bg=COLOR_ACCENT2, fg="white", relief="flat", width=24, state="disabled",
            command=self.dw_ambil_foto
        )
        self.dw_btn_ambil.grid(row=0, column=0, padx=10)

        tk.Button(
            btn_frame, text="Kembali ke Menu", font=("Segoe UI", 12),
            bg=COLOR_DANGER, fg="white", relief="flat", width=18,
            command=self.build_home
        ).grid(row=0, column=1, padx=10)

        self.start_camera()
        self.update_dw_camera()

    def update_dw_camera(self):
        if self.cam is None:
            return
        ret, frame = self.cam.read()
        if ret:
            self.last_frame_bgr = frame.copy()
            display = frame.copy()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            for (x, y, w, h) in faces:
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
            try:
                self.render_frame(display, self.dw_video_label)
            except tk.TclError:
                return
        self.camera_after_id = self.after(20, self.update_dw_camera)

    def dw_mulai(self):
        nama = self.dw_entry_nama.get().strip()
        password = self.dw_entry_password.get().strip()

        if nama == "":
            self.dw_status_var.set("Nama tidak boleh kosong.")
            return
        if password == "":
            self.dw_status_var.set("Password tidak boleh kosong.")
            return

        pastikan_folder_dataset()
        user_dir = os.path.join(DATASET_DIR, nama)
        os.makedirs(user_dir, exist_ok=True)

        users = load_users()
        users[nama] = {"password": hash_password(password)}
        save_users(users)

        file_lama = [
            f for f in os.listdir(user_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]

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
        if self.last_frame_bgr is None:
            return

        gray = cv2.cvtColor(self.last_frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            self.dw_status_var.set("Wajah tidak terdeteksi, posisikan ulang wajah anda.")
            return

        (x, y, w, h) = faces[0]
        face_img = cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)

        self.dw_sample_count += 1
        nomor_file = self.dw_offset + self.dw_sample_count
        filename = os.path.join(self.dw_user_dir, f"{self.dw_nama}_{nomor_file}.jpg")
        cv2.imwrite(filename, face_img)

        self.dw_btn_ambil.config(text=f"Ambil Foto Sample ({self.dw_sample_count}/{MIN_SAMPLES})")
        self.dw_status_var.set(f"Sample {self.dw_sample_count}/{MIN_SAMPLES} disimpan -> {filename}")

        if self.dw_sample_count >= MIN_SAMPLES:
            self.dw_btn_ambil.config(state="disabled")
            self.dw_status_var.set(f"Pendaftaran '{self.dw_nama}' selesai dengan {self.dw_sample_count} sample!")
            messagebox.showinfo(
                "Berhasil",
                f"Wajah '{self.dw_nama}' berhasil didaftarkan dengan {self.dw_sample_count} sample."
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app = App()
    app.mainloop()