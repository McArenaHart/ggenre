[CmdletBinding()]
param(
    [switch]$Reset,
    [switch]$RunTests,
    [switch]$NoServer,
    [switch]$RetryInterruptedAudio,
    [int]$FanVotes = 10,
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonExecutable = (Get-Command python -ErrorAction Stop).Source
}

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & $pythonExecutable @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python $($Args -join ' ')"
    }
}

Write-Host "Configuring local Django environment..."
$env:DJANGO_DEBUG = "True"
$env:LOCAL_CONSOLE_EMAIL = "True"

Write-Host "Applying migrations..."
Invoke-Python -Args @("manage.py", "migrate")

$setupArgs = @("manage.py", "setup_local_testing", "--fan-votes", "$FanVotes")
if ($Reset) {
    $setupArgs += "--reset"
}

Write-Host "Seeding local testing data..."
Invoke-Python -Args $setupArgs

if ($RunTests) {
    Write-Host "Running test suite..."
    Invoke-Python -Args @("manage.py", "test")
}

if (-not $NoServer) {
    $bind = "$ListenHost`:$Port"
    & $pythonExecutable -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ggenre.settings'); import django; django.setup(); from studio.audio_processing import available; import sys; sys.exit(0 if all(available().values()) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Studio audio engines are missing. Run: & '$pythonExecutable' -m pip install -r requirements-audio.txt"
    }
    Write-Host "Starting Studio audio worker with $pythonExecutable ..."
    $workerArgs = @("-u", "manage.py", "process_studio_audio")
    if ($RetryInterruptedAudio) {
        $workerArgs += "--retry-interrupted"
    }
    $audioWorker = Start-Process -FilePath $pythonExecutable -ArgumentList $workerArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot "studio-audio-worker.log") -RedirectStandardError (Join-Path $projectRoot "studio-audio-worker-error.log")
    try {
        Start-Sleep -Seconds 2
        if ($audioWorker.HasExited) {
            throw "Studio audio worker exited. Check studio-audio-worker-error.log."
        }
        Write-Host "Starting development server at http://$bind ..."
        Invoke-Python -Args @("manage.py", "runserver", $bind)
    } finally {
        if (-not $audioWorker.HasExited) { Stop-Process -Id $audioWorker.Id -ErrorAction SilentlyContinue }
    }
}
