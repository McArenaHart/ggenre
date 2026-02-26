[CmdletBinding()]
param(
    [switch]$Reset,
    [switch]$RunTests,
    [switch]$NoServer,
    [int]$FanVotes = 1,
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    & python @Args
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
    Write-Host "Starting development server at http://$bind ..."
    Invoke-Python -Args @("manage.py", "runserver", $bind)
}
