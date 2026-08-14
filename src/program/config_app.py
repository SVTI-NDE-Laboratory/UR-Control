"""Local browser app for editing and launching a measurement configuration."""

import html
import json
import os
import subprocess
import sys
import threading
import webbrowser
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


PROGRAM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROGRAM_DIR.parent.parent
CONFIG_DIR = PROGRAM_DIR / "config"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "config.json"
HTML_TEMPLATE_FILE = CONFIG_DIR / "config_app.html"
TEMP_CONFIG_FILE = CONFIG_DIR / "config_tmp.json"
STATE_FILE = CONFIG_DIR / "state.json"
MAIN_FILE = PROGRAM_DIR / "main.py"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "temporary_data"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
HOME_JOINT_TOLERANCE = 0.005

for folder in [ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
    stop_robot,
)


# The static page is read once. Each response only substitutes the small set of
# values that can change between runs.
HTML_TEMPLATE = HTML_TEMPLATE_FILE.read_text(encoding="utf-8")

SECTION_TITLES = {
    "line": "Measurement Line",
    "obstacle": "Obstacle",
    "motion": "Measurement Motion",
    "measurement": "Force Measurement",
}

FIELD_LABELS = {
    "length": "Total Length [cm]",
    "increment": "Increment [cm]",
    "direction_start_end": "Start-to-End Direction [x, y, z]",
    "start": "Start Position [cm]",
    "end": "End Position [cm]",
    "high_low_distance": "Obstacle Height [cm]",
    "direction_high_low": "High-to-Low Direction [x, y, z]",
    "program_path": "Robot Program Path",
    "contact_threshold": "Contact Threshold [N]",
    "holding_force": "Holding Force [N]",
    "max_displacement": "Maximum Displacement [cm]",
    "simulation": "Simulation",
    "type": "Motion Type (j/l)",
    "acceleration": "Acceleration [m/s²]",
    "speed": "Speed [m/s]",
    "force_step_distance": "Force Step Distance [cm]",
    "force_direction": "Force Direction [x, y, z]",
}

# These values remain fixed at their reviewed defaults and are submitted as
# hidden fields. They are intentionally not operator-adjustable in the app.
HIDDEN_FIELDS = {
    "direction_start_end",
    "direction_high_low",
    "program_path",
    "simulation",
    "force_direction",
}

# The program and JSON files use metres. Only these operator-facing form fields
# are converted to centimetres for display and converted back on submission.
CENTIMETRE_FIELDS = {
    "length",
    "increment",
    "start",
    "end",
    "high_low_distance",
    "max_displacement",
    "force_step_distance",
}


def display_value(value: Any) -> str:
    """Convert a JSON leaf value to its editable representation."""

    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def display_field_value(key: str, value: Any) -> str:
    """Return a field value in its operator-facing unit."""

    if key in CENTIMETRE_FIELDS:
        return str(value * 100)
    return display_value(value)


def parse_value(text: str, template: Any) -> Any:
    """Parse an edited value using the default value's JSON type."""

    text = text.strip()
    if isinstance(template, bool):
        if text.lower() not in {"true", "false"}:
            raise ValueError("must be true or false")
        return text.lower() == "true"
    if isinstance(template, list):
        parts = [part.strip() for part in text.split(",")]
        if not parts or any(not part for part in parts):
            raise ValueError("must be a comma-separated list of numbers")
        return [float(part) for part in parts]
    if isinstance(template, int) and not isinstance(template, bool):
        return int(text)
    if isinstance(template, float):
        return float(text)
    return text


def parse_field_value(key: str, text: str, template: Any) -> Any:
    """Parse a form field and convert displayed centimetres back to metres."""

    value = parse_value(text, template)
    if key in CENTIMETRE_FIELDS:
        return value / 100
    return value


def edited_config(defaults: dict[str, Any], fields: dict[str, list[str]]) -> dict[str, Any]:
    """Build a typed configuration from submitted form fields."""

    config = deepcopy(defaults)
    for section, values in defaults.items():
        if section == "obstacle":
            continue
        for key, template in values.items():
            field_name = f"{section}.{key}"
            if field_name not in fields:
                raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
            try:
                config[section][key] = parse_field_value(key, fields[field_name][0], template)
            except ValueError as error:
                label = FIELD_LABELS.get(key, key.replace("_", " ").title())
                raise ValueError(f"{label}: {error}") from error

    obstacle_enabled = fields.get("obstacle.enabled") == ["true"]
    high_low_enabled = (
        obstacle_enabled or fields.get("obstacle.high_low_enabled") == ["true"]
    )
    obstacle = {}
    selected_obstacle_keys = []
    if obstacle_enabled:
        selected_obstacle_keys.extend(("start", "end"))
    if high_low_enabled:
        selected_obstacle_keys.extend(("high_low_distance", "direction_high_low"))

    for key in selected_obstacle_keys:
        field_name = f"obstacle.{key}"
        if field_name not in fields:
            raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
        try:
            obstacle[key] = parse_field_value(
                key, fields[field_name][0], defaults["obstacle"][key]
            )
        except ValueError as error:
            label = FIELD_LABELS.get(key, key.replace("_", " ").title())
            raise ValueError(f"{label}: {error}") from error

    if obstacle:
        config["obstacle"] = obstacle
    else:
        config.pop("obstacle", None)

    measurement = config["measurement"]
    if (
        measurement["contact_threshold"] == 0
        and measurement["holding_force"] == 0
    ):
        measurement["simulation"] = True
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    """Reject values that would make motion planning invalid or unsafe."""

    line = config["line"]
    obstacle = config.get("obstacle") or {}
    motion = config["motion"]
    measurement = config["measurement"]

    positive_values = {
        "Line length": line["length"],
        "Line increment": line["increment"],
        "Maximum displacement": measurement["max_displacement"],
        "Acceleration": motion["acceleration"],
        "Speed": motion["speed"],
    }
    if "high_low_distance" in obstacle:
        positive_values["High-to-low distance"] = obstacle["high_low_distance"]
    if "force_step_distance" in measurement:
        positive_values["Force step distance"] = measurement["force_step_distance"]

    for label, value in positive_values.items():
        if value <= 0:
            raise ValueError(f"{label} must be greater than zero.")

    contact_threshold = measurement["contact_threshold"]
    holding_force = measurement["holding_force"]
    if contact_threshold < 0 or holding_force < 0:
        raise ValueError("Contact and holding force cannot be negative.")
    if (contact_threshold == 0) != (holding_force == 0):
        raise ValueError(
            "Contact and holding force must either both be zero for simulation "
            "or both be greater than zero."
        )
    if holding_force < contact_threshold:
        raise ValueError("Holding force must be greater than or equal to contact force.")

    if motion["type"].lower() != "l":
        raise ValueError("Measurement motion type must be 'l'.")

    has_start = "start" in obstacle
    has_end = "end" in obstacle
    if has_start != has_end:
        raise ValueError("Obstacle start and end must both be enabled.")
    has_high_low_distance = "high_low_distance" in obstacle
    has_high_low_direction = "direction_high_low" in obstacle
    if has_high_low_distance != has_high_low_direction:
        raise ValueError("High-to-low distance and direction must both be enabled.")
    if has_start and not has_high_low_distance:
        raise ValueError("High-to-low minimum distance is required when an obstacle exists.")
    if has_start and not 0 <= obstacle["start"] <= obstacle["end"] <= line["length"]:
        raise ValueError(
            "Obstacle positions must satisfy 0 <= start <= end <= line length."
        )

    vectors = [
        ("Start-to-end direction", line["direction_start_end"]),
    ]
    if has_high_low_direction:
        vectors.append(("High-to-low direction", obstacle["direction_high_low"]))
    if "force_direction" in measurement:
        vectors.append(("Force direction", measurement["force_direction"]))
    for label, vector in vectors:
        if len(vector) != 3 or not any(vector):
            raise ValueError(f"{label} must contain three numbers and cannot be zero.")

    if not measurement["program_path"].strip():
        raise ValueError("Robot program path cannot be empty.")


def form_html(
    config: dict[str, Any],
    defaults: dict[str, Any] | None = None,
    message: str = "",
    error: bool = False,
    output_directory: Path = DEFAULT_OUTPUT_DIR,
    show_terminal: bool = False,
) -> str:
    """Return the complete launcher page."""

    if defaults is None:
        defaults = config

    def current_value(section: str, key: str) -> Any:
        return (config.get(section) or {}).get(key, defaults[section][key])

    def value_text(section: str, key: str) -> str:
        return html.escape(
            display_field_value(key, current_value(section, key)), quote=True
        )

    def input_html(section: str, key: str, attributes: str = "required") -> str:
        name = html.escape(f"{section}.{key}", quote=True)
        label = html.escape(FIELD_LABELS.get(key, key.replace("_", " ").title()), quote=True)
        return (
            f'<input id="{name}" name="{name}" value="{value_text(section, key)}" '
            f'aria-label="{label}" {attributes}>'
        )

    hidden_controls = []
    for section, keys in {
        "line": ("direction_start_end",),
        "obstacle": ("direction_high_low",),
        "measurement": ("program_path", "simulation", "force_direction"),
    }.items():
        for key in keys:
            if key not in defaults.get(section, {}):
                continue
            optional = ' data-optional-group="high-low"' if section == "obstacle" else ""
            hidden_controls.append(
                f'<input type="hidden" name="{section}.{key}" '
                f'value="{value_text(section, key)}"{optional}>'
            )

    length = input_html("line", "length")
    increment = input_html("line", "increment")
    measurement_count = max(
        2,
        int(
            current_value("line", "length")
            / current_value("line", "increment")
            + 1e-9
        )
        + 1,
    )
    sections = [
        '<fieldset><legend>Measurement Line</legend>'
        f'<div class="parameter-row single"><label for="line.length">Total Length [cm]</label>{length}</div>'
        '<div class="parameter-row double line-spacing-row">'
        f'<span>Increment [cm] / # Measurements</span>{increment}'
        f'<input id="measurement-count" type="number" min="2" step="1" value="{measurement_count}" aria-label="Number of measurements" required>'
        '</div></fieldset>'
    ]

    obstacle = config.get("obstacle") or {}
    obstacle_checked = " checked" if "start" in obstacle and "end" in obstacle else ""
    high_low_checked = " checked" if "high_low_distance" in obstacle and "direction_high_low" in obstacle else ""
    start = input_html("obstacle", "start", 'data-optional-group="obstacle-position"')
    end = input_html("obstacle", "end", 'data-optional-group="obstacle-position"')
    height = input_html("obstacle", "high_low_distance", 'data-optional-group="high-low"')
    sections.append(
        '<fieldset id="obstacle-fields"><legend>Obstacle</legend>'
        '<div class="toggle-row">'
        '<label class="option-toggle"><input id="obstacle-enabled" name="obstacle.enabled" type="checkbox" value="true"'
        f'{obstacle_checked}>Obstacle Exists</label>'
        '<label class="option-toggle"><input id="high-low-enabled" name="obstacle.high_low_enabled" type="checkbox" value="true"'
        f'{high_low_checked}>Obstacle Height Exists</label></div>'
        '<div class="parameter-row double obstacle-position-row" data-optional-group="obstacle-position">'
        f'<span>Positions Start / End [cm]</span>{start}{end}</div>'
        '<div class="parameter-row single" data-optional-group="high-low">'
        f'<label for="obstacle.high_low_distance">Obstacle Height [cm]</label>{height}</div>'
        '</fieldset>'
    )

    speed = input_html("motion", "speed")
    acceleration = input_html("motion", "acceleration")
    hidden_controls.append('<input type="hidden" name="motion.type" value="l">')
    sections.append(
        '<fieldset><legend>Measurement Motion <span class="legend-note">Linear (l)</span></legend>'
        f'<div class="parameter-row single"><label for="motion.speed">Speed [m/s]</label>{speed}</div>'
        f'<div class="parameter-row single"><label for="motion.acceleration">Acceleration [m/s²]</label>{acceleration}</div>'
        '</fieldset>'
    )

    contact = input_html("measurement", "contact_threshold")
    holding = input_html("measurement", "holding_force")
    maximum = input_html("measurement", "max_displacement")
    measurement_controls = (
        f'<div class="parameter-row double force-row"><span>Force Contact / Holding [N]</span>{contact}{holding}</div>'
        '<div class="parameter-row single">'
        f'<label for="measurement.max_displacement">Maximum Displacement [cm]</label>{maximum}</div>'
    )
    for key, default_value in defaults["measurement"].items():
        if key in {"program_path", "simulation", "force_direction", "contact_threshold", "holding_force", "max_displacement"}:
            continue
        label = html.escape(FIELD_LABELS.get(key, key.replace("_", " ").title()))
        measurement_controls += (
            '<div class="parameter-row single">'
            f'<label for="measurement.{key}">{label}</label>'
            f'{input_html("measurement", key)}</div>'
        )
    sections.append(
        f'<fieldset><legend>Force Measurement</legend>{measurement_controls}</fieldset>'
    )

    status = ""
    if message:
        status_class = "status error" if error else "status success"
        status = f'<p class="{status_class}">{html.escape(message)}</p>'

    output_directory_value = html.escape(str(output_directory), quote=True)
    terminal_checked = " checked" if show_terminal else ""

    replacements = {
        "{{STATUS}}": status,
        "{{HIDDEN_CONTROLS}}": "".join(hidden_controls),
        "{{OUTPUT_DIRECTORY}}": output_directory_value,
        "{{TERMINAL_CHECKED}}": terminal_checked,
        "{{SECTIONS}}": "".join(sections),
    }
    page = HTML_TEMPLATE
    for placeholder, value in replacements.items():
        page = page.replace(placeholder, value)
    return page


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


def assert_safe_start_position() -> None:
    """Connect read-only and reject a web launch unless the robot is at Home."""

    routines_data = read_routines_file(ROUTINES_FILE)
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
    config: dict[str, Any], output_directory: Path, show_terminal: bool
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
        "--output-dir",
        str(output_directory),
    ]

    if show_terminal:
        (output_directory / "program.log").write_text(
            "Program output is shown in the visible terminal for this run.\n",
            encoding="utf-8",
        )
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        return subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            creationflags=creationflags,
            start_new_session=False,
        )

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (output_directory / "program.log").open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    return process


class ConfigRequestHandler(BaseHTTPRequestHandler):
    """Serve the local config form and handle its Start action."""

    defaults: dict[str, Any]
    display_config: dict[str, Any]
    output_directory: Path
    state_file: Path
    show_terminal: bool = False
    worker_process: subprocess.Popen | None = None
    worker_lock = threading.Lock()

    def _send_page(self, message: str = "", error: bool = False, status: int = 200) -> None:
        body = form_html(
            self.display_config,
            self.defaults,
            message,
            error,
            self.output_directory,
            self.show_terminal,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_state(self) -> None:
        """Return the current state file as JSON without modifying it."""

        with self.__class__.worker_lock:
            process = self.__class__.worker_process
            program_running = process is not None and process.poll() is None

        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            state = {"mode": "state unavailable", "message": str(error)}
        state["program_running"] = program_running
        body = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/state":
            self._send_state()
            return
        if parsed_path.path == "/select-directory":
            try:
                selected_path = choose_directory()
                body = json.dumps(
                    {"path": str(selected_path) if selected_path else None}
                ).encode("utf-8")
            except (OSError, subprocess.SubprocessError) as error:
                body = json.dumps({"error": str(error)}).encode("utf-8")
                self.send_response(500)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path != "/":
            self.send_error(404)
            return
        self._send_page()

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        request_path = urlparse(self.path).path
        if request_path == "/close":
            self._close_app()
            return
        if request_path == "/stop":
            self._stop_worker()
            return
        if request_path != "/start":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65_536:
                raise ValueError("Submitted configuration is too large.")
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            if fields.get("operator_confirmation") != ["confirmed"]:
                raise ValueError("Safety confirmation is required before starting the program.")
            output_value = fields.get("output_directory", [""])[0].strip()
            if not output_value:
                raise ValueError("A data folder is required.")
            output_directory = Path(output_value).expanduser()
            if not output_directory.is_absolute():
                raise ValueError("The data folder must be an absolute path.")
            output_directory = output_directory.resolve()
            show_terminal = fields.get("show_terminal") == ["true"]
            config = edited_config(self.defaults, fields)
            with self.__class__.worker_lock:
                current_process = self.__class__.worker_process
                if current_process is not None and current_process.poll() is None:
                    raise ValueError("A program is already running. Stop it before starting another.")
                self.__class__.display_config = config
                self.__class__.output_directory = output_directory
                self.__class__.state_file = output_directory / "state.json"
                self.__class__.show_terminal = show_terminal
                output_directory.mkdir(parents=True, exist_ok=True)
                write_json_atomic(
                    self.__class__.state_file,
                    {"mode": "checking_home"},
                )
                assert_safe_start_position()
                self.__class__.worker_process = start_program(
                    config, output_directory, show_terminal
                )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, UnsafeStartPositionError):
                write_json_atomic(
                    self.__class__.state_file,
                    {"mode": "unsafe_start", "message": str(error)},
                )
            self._send_page(str(error), error=True, status=400)
            return

        self.send_response(303)
        # The live Program state panel already reports startup. Redirecting
        # with a persistent ?started banner made later Close actions look like
        # they had launched another program.
        self.send_header("Location", "/")
        self.end_headers()

    def _stop_worker(self) -> None:
        """Stop robot motion, terminate the worker, and report JSON status."""

        with self.__class__.worker_lock:
            stopped, stop_error = self._stop_worker_locked(
                "control panel Stop button"
            )
            if not stopped:
                body = json.dumps({"error": "No program is currently running."}).encode("utf-8")
                self.send_response(409)
            elif stop_error is None:
                body = json.dumps({"stopped": True}).encode("utf-8")
                self.send_response(200)
            else:
                body = json.dumps(
                    {"error": f"Python stopped, but the robot stop command failed: {stop_error}"}
                ).encode("utf-8")
                self.send_response(502)

        self._send_json_body(body)

    def _stop_worker_locked(self, reason: str) -> tuple[bool, Exception | None]:
        """Stop an active worker while ``worker_lock`` is held."""

        process = self.__class__.worker_process
        if process is None or process.poll() is not None:
            self.__class__.worker_process = None
            return False, None

        stop_error = None
        try:
            # Command the robot before terminating Python, since a hard process
            # termination cannot run the worker's finally block.
            stop_robot(ROBOT_IP)
        except Exception as error:
            stop_error = error
        try:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except Exception as error:
            if stop_error is None:
                stop_error = error
        finally:
            self.__class__.worker_process = None

        if stop_error is None:
            write_json_atomic(
                self.__class__.state_file,
                {"mode": "stopped", "reason": reason},
            )
        else:
            write_json_atomic(
                self.__class__.state_file,
                {
                    "mode": "error",
                    "message": f"Python stopped, but the robot stop command failed: {stop_error}",
                },
            )
        return True, stop_error

    def _close_app(self) -> None:
        """Stop an active run, respond, and then shut down the web app."""

        with self.__class__.worker_lock:
            stopped, stop_error = self._stop_worker_locked(
                "control panel Close app button"
            )

        response = {"closed": True, "worker_stopped": stopped}
        if stop_error is not None:
            response["warning"] = (
                "The app closed after a stop error: " + str(stop_error)
            )
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)

        self._send_json_body(body)
        # shutdown() must run outside the request thread to avoid waiting for
        # this handler to finish its response. Closing always shuts down the
        # app, even if the best-effort robot stop reported an error.
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _send_json_body(self, body: bytes) -> None:
        """Finish a JSON response after its status has been selected."""

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep routine browser requests out of the operator terminal."""


def main() -> None:
    defaults = json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
    validate_config(defaults)
    ConfigRequestHandler.defaults = defaults
    ConfigRequestHandler.display_config = defaults
    ConfigRequestHandler.output_directory = DEFAULT_OUTPUT_DIR
    ConfigRequestHandler.state_file = STATE_FILE
    ConfigRequestHandler.show_terminal = False

    server = ThreadingHTTPServer(("127.0.0.1", 0), ConfigRequestHandler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Configuration app: {url}")
    print("Press Ctrl+C here to close the configuration app.")
    threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nConfiguration app closed.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
