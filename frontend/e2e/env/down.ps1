# Stop the test API and web app started by up.ps1 (only the processes recorded in .runtime\pids.json).
param([switch]$Quiet)
$Runtime = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path '.runtime'
$file = Join-Path $Runtime 'pids.json'
if (-not (Test-Path $file)) { if (-not $Quiet) { Write-Host 'Test environment was not running.' }; return }
$pids = Get-Content $file -Raw | ConvertFrom-Json
foreach ($id in @($pids.api, $pids.web)) {
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    # only kill a python/node process (guards against a recycled process id)
    if ($proc -and @('python', 'node') -contains $proc.ProcessName) { & taskkill /PID $id /T /F | Out-Null }
}
Remove-Item $file -Force
if (-not $Quiet) { Write-Host 'Test environment stopped.' }
