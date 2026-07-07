import pyaudio
import wave

# LIHAT ID MIC DARI HASIL SEBELUMNYA:
# ID 1 = Rexus SW-10 Webcam
# ID 2 = USB Composite Device
ID_MIC_YANG_DITES = 1  # <-- Ganti angka ini (1 atau 2) untuk menguji masing-masing mic

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000
CHUNK = 1024
RECORD_SECONDS = 5
WAVE_OUTPUT_FILENAME = f"tes_suara_mic_ID_{ID_MIC_YANG_DITES}.wav"

p = pyaudio.PyAudio()

print(f"=== MENCOBA REKAM LEWAT MIC ID: {ID_MIC_YANG_DITES} ===")
try:
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    input_device_index=ID_MIC_YANG_DITES, # Mengunci ID Mic
                    frames_per_buffer=CHUNK)
except Exception as e:
    print(f"? Error: Tidak bisa membuka Mic ID {ID_MIC_YANG_DITES}. Pesan: {e}")
    p.terminate()
    exit()

print("?? MULAI REKAM... Silahkan bicara dekat mic: 'Tes Satu Dua Tiga'...")
frames = []

for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK, exception_on_overflow=False)
    frames.append(data)

print("?? SELESAI MEREKAM.")

stream.stop_stream()
stream.close()
p.terminate()

# Simpan hasil rekaman menjadi file audio .wav
wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
wf.setnchannels(CHANNELS)
wf.setsampwidth(p.get_sample_size(FORMAT))
wf.setframerate(RATE)
wf.writeframes(b''.join(frames))
wf.close()

print(f"? File suara berhasil disimpan dengan nama: {WAVE_OUTPUT_FILENAME}")
print("Silahkan buka File Manager Raspi Anda, lalu putar file tersebut menggunakan headset/speaker untuk mendengar hasilnya!")
