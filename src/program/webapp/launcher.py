"""Preflight checks and measurement worker process management."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__:
    from .settings import (
        HOME_JOINT_TOLERANCE,
        MAIN_FILE,
        PROJECT_ROOT,
        ROBOT_IP,
        TEMP_CONFIG_FILE,
    )
else:
    from settings import (
        HOME_JOINT_TOLERANCE,
        MAIN_FILE,
        PROJECT_ROOT,
        ROBOT_IP,
        TEMP_CONFIG_FILE,
    )

from read_routines import get_waypoint, read_routines_file
from robot_connection import assert_at_home, assert_robot_running, get_rtde_receive


def choose_directory() -> Path | None:
    """Open the native Windows folder picker and return its selection."""

    if os.name != "nt":
        raise OSError("The folder picker is currently available on Windows only.")

    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = 'Select the folder for run data'; "
        "$dialog.ShowNewFolderButton = $true; "
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
        "{ [Console]::Write($dialog.SelectedPath) }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "Folder picker failed.")
    selected_path = result.stdout.strip()
    return Path(selected_path) if selected_path else None


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Write JSON without exposing a partially written file to the UI."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def assert_safe_start_position(routine_file: Path) -> None:
    """Connect read-only and reject a web launch unless the robot is at Home."""

    routines_data = read_routines_file(routine_file)
    home = get_waypoint(routines_data, "Home")
    if "q" not in home:
        raise ValueError("The Home waypoint has no joint target for startup verification.")

    assert_robot_running(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)
    try:
        assert_at_home(rtde_receive, home["q"], HOME_JOINT_TOLERANCE)
    finally:
        rtde_receive.disconnect()


def start_program(
    config: dict[str, Any],
    output_directory: Path,
    show_terminal: bool,
    routine_file: Path,
) -> subprocess.Popen:
    """Write the temporary config and launch main.py visibly or in the background."""

    TEMP_CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    output_directory.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_directory / "config_used.json", config)
    write_json_atomic(output_directory / "state.json", {"mode": "starting"})

    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console_python = executable.with_name("python.exe")
        if console_python.exists():
            executable = console_python

    command = [
        str(executable),
        "-u",
        str(MAIN_FILE),
        "--config",
        str(TEMP_CONFIG_FILE),
        "--operator-confirmed",
        "--routines-file",
        str(routine_file),
        "--output-dir",
        str(output_directory),
    ]

    if show_terminal:
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        return subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            creationflags=creationflags,
            start_new_session=False,
        )

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
