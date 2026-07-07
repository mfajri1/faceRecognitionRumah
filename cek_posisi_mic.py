import pyaudio
import numpy as np

# Coba ganti angka ini antara 1 atau 2 sesuai ID mic Anda sebelumnya
ID_MIC = 1  

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 48000
CHUNK = 1024

p = pyaudio.PyAudio()

print(f"=== MEMULAI TES VISUAL MIC ID: {ID_MIC} ===")
print("Dekatkan mulut ke mic dan bicaralah. Lihat apakah grafik batangan (||||) bergerak naik-turun.")
print("Tekan Ctrl+C untuk berhenti.\n")

try:
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    input_device_index=ID_MIC,
                    frames_per_buffer=CHUNK)
except Exception as e:
    print(f"❌ Gagal membuka Mic ID {ID_MIC}: {e}")
    p.terminate()
    exit()

try:
    while True:
        # Baca data biner dari mic
        data = stream.read(CHUNK, exception_on_overflow=False)
        # Ubah data biner menjadi array angka tingkat kekencangan suara
        audio_data = np.frombuffer(data, dtype=np.int16)
        # Hitung rata-rata amplitudo (volume)
        volume = np.abs(audio_data).mean()
        
        # Buat grafik batangan sederhana berdasarkan intensitas volume
        bar_length = int(volume / 100)
        bar = "█" * min(bar_length, 50)  # Batasi panjang grafik maksimal 50 karakter
        
        # Cetak grafik real-time di baris yang sama
        print(f"Volume Mic: {int(volume):<5} {bar:<50}", end="\r")
except KeyboardInterrupt:
    print("\n⏹️ Pengujian dihentikan.")

stream.stop_stream()
stream.close()
p.terminate()
