# Create / reset the TEST database and start the test API (port 8100) and test web app (port 5190).
#   powershell -ExecutionPolicy Bypass -File frontend\e2e\env\up.ps1 [-NoReset]
# Never touches the real database (opetional_agents), the real servers (8000/5180) or C:\Users\shri\.operation-agents.
param([switch]$NoReset)
$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Runtime = Join-Path $Frontend 'e2e\.runtime'
$ApiPort = if ($env:E2E_API_PORT) { [int]$env:E2E_API_PORT } else { 8100 }
$WebPort = if ($env:E2E_WEB_PORT) { [int]$env:E2E_WEB_PORT } else { 5190 }
if (@(8000, 8001, 5180, 5181) -contains $ApiPort -or @(8000, 8001, 5180, 5181) -contains $WebPort) { throw "Ports $ApiPort/$WebPort belong to the real servers." }
New-Item -ItemType Directory -Force $Runtime | Out-Null

# one test environment at a time: stop ours if it is running
& (Join-Path $PSScriptRoot 'down.ps1') -Quiet

foreach ($p in @($ApiPort, $WebPort)) {
    if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) { throw "Port $p is already in use by something that is not this test environment." }
}

function Run-Py([string]$Command) {
    Push-Location $Backend
    try { & python -m scripts.e2e_env $Command; if ($LASTEXITCODE -ne 0) { throw "e2e_env $Command failed ($LASTEXITCODE)" } } finally { Pop-Location }
}

if (-not $NoReset) {
    Run-Py 'reset-db'
    Run-Py 'migrate'
    Run-Py 'seed'
}
Run-Py 'reset-mail'

# API: scripts.e2e_env serve forces the safe settings itself
$api = Start-Process -FilePath python -ArgumentList '-m', 'scripts.e2e_env', 'serve' -WorkingDirectory $Backend -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $Runtime 'api.out.log') -RedirectStandardError (Join-Path $Runtime 'api.err.log')

# Web: vite on the test port, pointed at the test API
$env:VITE_API_BASE_URL = "http://localhost:$ApiPort"
$web = Start-Process -FilePath node -ArgumentList 'node_modules/vite/bin/vite.js', '--port', $WebPort, '--strictPort', '--host', '127.0.0.1' -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $Runtime 'web.out.log') -RedirectStandardError (Join-Path $Runtime 'web.err.log')
Remove-Item Env:\VITE_API_BASE_URL -ErrorAction SilentlyContinue

@{ api = $api.Id; web = $web.Id; apiPort = $ApiPort; webPort = $WebPort } | ConvertTo-Json | Set-Content (Join-Path $Runtime 'pids.json')

function Wait-Url([string]$Url, [int]$Seconds) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        try { if ((Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5).StatusCode -lt 500) { return } } catch { }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $Url (see $Runtime\*.log)"
}
Wait-Url "http://localhost:$ApiPort/health" 300
Wait-Url "http://localhost:$WebPort/" 120
Write-Host "Test environment is up: API http://localhost:$ApiPort  web http://localhost:$WebPort  (database opetional_agents_test)"
