# Gracefully restart Brave with --remote-debugging-port=9222 against the
# user's default profile. Brave's session-restore brings back tabs and the
# ChatGPT login cookies stay in the default user-data-dir.
#
# Sequence:
#   1. CloseMainWindow() on top-level Brave windows (sends WM_CLOSE so
#      Chromium runs its normal shutdown path and writes "Last Session"
#      data that session-restore reads next launch).
#   2. Wait up to 30s for processes to exit.
#   3. Force-kill any helper processes still alive (rare residual GPU/
#      Crashpad procs).
#   4. Launch Brave with the CDP flag.
#   5. Poll for CDP port 9222 to be Listen, return non-zero on timeout.

$ErrorActionPreference = "Stop"

$BravePath = "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
$UserDataDir = "C:\Users\user\AppData\Local\BraveSoftware\Brave-Browser\User Data"

if (-not (Test-Path $BravePath)) {
    Write-Host "ERROR: brave.exe not found at $BravePath"
    exit 2
}

# Step 1: graceful close
$mainWindows = Get-Process brave -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 }
Write-Host "graceful close: $($mainWindows.Count) top-level window(s)"
foreach ($p in $mainWindows) {
    try { [void]$p.CloseMainWindow() } catch { }
}

# Step 2: wait for exit (poll every 1s, cap 30s)
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    $remaining = Get-Process brave -ErrorAction SilentlyContinue
    if (-not $remaining) { break }
    Start-Sleep -Seconds 1
}
$remaining = Get-Process brave -ErrorAction SilentlyContinue
Write-Host "after graceful wait: $(($remaining | Measure-Object).Count) brave proc(s) remain"

# Step 3: force-kill stragglers
if ($remaining) {
    $remaining | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# Step 4: launch with CDP
Write-Host "launching brave with CDP=9222 + default profile"
Start-Process -FilePath $BravePath `
    -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=`"$UserDataDir`""

# Step 5: poll for port 9222 listen
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    $listen = Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
    if ($listen) {
        Write-Host "CDP port 9222 LISTEN (PID=$($listen.OwningProcess[0]))"
        exit 0
    }
    Start-Sleep -Seconds 1
}
Write-Host "ERROR: CDP port 9222 did not come up within 30s"
exit 3
