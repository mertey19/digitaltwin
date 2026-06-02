# Tek seferlik sunucu testi — start_server.log olusturur (CI/agent icin)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "start_server.log"

@(
    "=== serve.py test $(Get-Date -Format o) ==="
    "CWD: $PWD"
) | Set-Content $log

try {
    $pyVer = & python --version 2>&1
    "Python: $pyVer" | Add-Content $log
} catch {
    "Python: NOT FOUND" | Add-Content $log
    exit 1
}

$stdout = Join-Path $PSScriptRoot "serve_stdout.log"
$stderr = Join-Path $PSScriptRoot "serve_stderr.log"
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

$p = Start-Process -FilePath "python" `
    -ArgumentList "serve.py", "--no-browser" `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru -NoNewWindow

Start-Sleep -Seconds 3

try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/twin.html" -UseBasicParsing -TimeoutSec 5
    "--- curl probe ---" | Add-Content $log
    "HTTP $($r.StatusCode) len=$($r.RawContentLength)" | Add-Content $log
} catch {
    "--- curl probe ---" | Add-Content $log
    "FAIL: $($_.Exception.Message)" | Add-Content $log
}

if ($p -and -not $p.HasExited) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}

if (Test-Path $stdout) {
    "--- stdout ---" | Add-Content $log
    Get-Content $stdout | Add-Content $log
}
if (Test-Path $stderr) {
    "--- stderr ---" | Add-Content $log
    Get-Content $stderr | Add-Content $log
}

Write-Host "Log: $log"
Get-Content $log
