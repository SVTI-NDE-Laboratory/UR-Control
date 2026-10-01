param(
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

function Get-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return "python"
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return "py -3"
    }

    throw "Python was not found. Install Python 3.12 or newer, then run this script again."
}

$pythonCommand = Get-PythonCommand

Write-Host "Creating virtual environment at $VenvPath"
Invoke-Expression "$pythonCommand -m venv `"$VenvPath`""

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Could not find virtual environment Python at $venvPython"
}

Write-Host "Upgrading pip"
& $venvPython -m pip install --upgrade pip

Write-Host "Installing project requirements"
& $venvPython -m pip install -r requirements.txt

Write-Host "Checking required imports"
& $venvPython -c "import fastapi, pydantic, uvicorn, rtde_io, rtde_receive; print('Import check OK')"

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run the CLI program with:"
Write-Host "  .\$VenvPath\Scripts\python.exe src\program\main.py --config documentation\company_run\config_server.json --routines-file documentation\company_run\routine.json --output-dir documentation\company_run\output"
