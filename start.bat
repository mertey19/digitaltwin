@echo off
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo  Dijital Ikiz - Yerel HTTP Sunucusu
echo ========================================
echo  Klasor: %CD%
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo HATA: Python bulunamadi. https://www.python.org/downloads/ adresinden kurun.
    echo Kurulumda "Add python.exe to PATH" secenegini isaretleyin.
    pause
    exit /b 1
)

echo Bagimliliklar kontrol ediliyor...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo HATA: pip install basarisiz.
    pause
    exit /b 1
)

echo.
echo Sunucu baslatiliyor (bu pencereyi KAPATMAYIN)...
echo.
echo   Tarayici adresi:  http://localhost:8000/twin.html
echo   Ana sayfa:        http://localhost:8000/
echo.
echo Durdurmak icin bu pencerede Ctrl+C yapin.
echo.

python serve.py --no-browser
if errorlevel 1 (
    echo.
    echo HATA: serve.py cikti kodu %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

pause
