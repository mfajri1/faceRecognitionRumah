#!/bin/bash
# ============================================================
#  Setup Virtual Environment (Python 3.10) - Linux / macOS
# ============================================================

set -e

echo "Mengecek Python 3.10..."

if command -v python3.10 &> /dev/null; then
    PYTHON_BIN=python3.10
else
    echo ""
    echo "[ERROR] python3.10 tidak ditemukan di sistem."
    echo "Install dulu, contoh di Ubuntu/Debian:"
    echo "    sudo apt update"
    echo "    sudo apt install python3.10 python3.10-venv"
    echo ""
    echo "Untuk PyAudio (microphone), install juga:"
    echo "    sudo apt install portaudio19-dev"
    exit 1
fi

echo "Python 3.10 ditemukan ($($PYTHON_BIN --version)). Membuat virtual environment 'venv'..."
$PYTHON_BIN -m venv venv

echo "Mengaktifkan venv dan menginstall requirements..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "============================================================"
echo " Setup selesai!"
echo " Venv aktif. Untuk menjalankan program:"
echo "     python sistem_face_password.py"
echo ""
echo " Lain kali, aktifkan venv dulu dengan:"
echo "     source venv/bin/activate"
echo "============================================================"