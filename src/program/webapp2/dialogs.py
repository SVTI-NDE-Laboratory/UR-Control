"""Native dialogs used by the WebApp2 launcher and its local Settings page."""

import os
from pathlib import Path
import subprocess


def choose_local_data(missing=False):
    if os.name != "nt":
        raise OSError("Select a local data folder using --data-dir on this platform.")
    description = ("RTM Cobot Studio local data was not found. Select its folder, or an empty folder to create it."
                   if missing else "Select a local data folder, or an empty folder to copy the current data into.")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        f"$dialog.Description = '{description}'; "
        "$dialog.ShowNewFolderButton = $true; "
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Write($dialog.SelectedPath) }"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        raise OSError(result.stderr.strip() or "Could not open the local data folder chooser.")
    return Path(result.stdout.strip()).resolve() if result.stdout.strip() else None


def choose_routine_script(directory):
    """Use a native picker because browsers cannot set a file input's directory."""
    if os.name != "nt":
        raise OSError("The script chooser is currently available on Windows only.")
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError("The routine scripts directory does not exist. Check app_config.")
    # Pass the path as data, including apostrophes, rather than interpolating it into PowerShell.
    environment = os.environ.copy()
    environment["UR15_SCRIPT_PICKER_DIRECTORY"] = str(directory)
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
        "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
        "$dialog.Title = 'Choose a PolyScope script'; "
        "$dialog.InitialDirectory = $env:UR15_SCRIPT_PICKER_DIRECTORY; "
        "$dialog.Filter = 'PolyScope scripts (*.script)|*.script'; "
        "$dialog.CheckFileExists = $true; $dialog.Multiselect = $false; "
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Write($dialog.FileName) }"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-Command", script],
                            env=environment, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        raise OSError(result.stderr.strip() or "Could not open the script chooser.")
    return Path(result.stdout.strip()).resolve() if result.stdout.strip() else None
