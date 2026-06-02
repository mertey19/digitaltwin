# Dijital Ikiz - yerel HTTP sunucusu (serve.py)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "========================================"
Write-Host " Dijital Ikiz - Yerel HTTP Sunucusu"
Write-Host "========================================"
Write-Host " Klasor: $PWD"
Write-Host ""

try {
    $pyVer = & python --version 2>&1
    Write-Host "Python: $pyVer"
} catch {
    Write-Host "HATA: Python bulunamadi. https://www.python.org/downloads/ adresinden kurun." -ForegroundColor Red
    Read-Host "Devam etmek icin Enter"
    exit 1
}

Write-Host "Bagimliliklar kontrol ediliyor..."
& python -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "HATA: pip install basarisiz (kod $LASTEXITCODE)" -ForegroundColor Red
    Read-Host "Devam etmek icin Enter"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Sunucu baslatiliyor (bu pencereyi KAPATMAYIN)..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Tarayici adresi:  http://localhost:8000/twin.html" -ForegroundColor Cyan
Write-Host "  Ana sayfa:        http://localhost:8000/" -ForegroundColor Cyan
Write-Host ""
Write-Host "Durdurmak icin Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

try {
    & python serve.py --no-browser
    if ($LASTEXITCODE -ne 0) { throw "serve.py cikti kodu $LASTEXITCODE" }
} catch {
    Write-Host ""
    Write-Host "HATA: $_" -ForegroundColor Red
    Read-Host "Devam etmek icin Enter"
    exit 1
}
