@echo off
REM ============================================================
REM  Setup Virtual Environment (Python 3.10) - Windows
REM ============================================================

echo Mengecek Python 3.10...

py -3.10 --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python 3.10 tidak ditemukan lewat "py -3.10".
    echo Pastikan Python 3.10 sudah terinstall dan tercentang
    echo "Add python.exe to PATH" saat instalasi.
    echo Download di: https://www.python.org/downloads/release/python-3100/
    pause
    exit /b 1
)

echo Python 3.10 ditemukan. Membuat virtual environment "venv"...
py -3.10 -m venv venv

echo Mengaktifkan venv dan menginstall requirements...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ============================================================
echo  Setup selesai!
echo  Venv aktif. Untuk menjalankan program:
echo      python sistem_face_password.py
echo.
echo  Lain kali, aktifkan venv dulu dengan:
echo      venv\Scripts\activate.bat
echo ============================================================
echo.

cmd /k