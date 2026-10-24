param(
    [switch]$NoBrowser,
    [int]$Port = 8501
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install requirements.txt first. See README.md.'
}
$siteUrl = 'http://127.0.0.1:' + $Port
$healthUrl = $siteUrl + '/_stcore/health'
function Test-MapServer {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok'
    } catch { return $false }
}
if (-not (Test-MapServer)) {
    $appPath = Join-Path $PSScriptRoot 'app.py'
    $serverArguments = @('-m', 'streamlit', 'run', ('"' + $appPath + '"'),
        '--server.address', '127.0.0.1', '--server.port', $Port,
        '--server.headless', 'true', '--browser.gatherUsageStats', 'false')
    Start-Process -FilePath $pythonPath -ArgumentList $serverArguments -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'web.stdout.log') `
        -RedirectStandardError (Join-Path $PSScriptRoot 'web.stderr.log') | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-MapServer) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'The website did not start. Check web.stderr.log.' }
}
Write-Output ('HUFS shade map is running: ' + $siteUrl)
if (-not $NoBrowser) { Start-Process $siteUrl }
