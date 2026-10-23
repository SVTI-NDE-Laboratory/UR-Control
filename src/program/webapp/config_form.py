"""Configuration form parsing, validation, and HTML rendering."""

import html
from copy import deepcopy
from typing import Any

if __package__:
    from .settings import (
        FIELD_LABELS,
        HTML_TEMPLATE_FILE,
        ROUTINES_FILE,
    )
else:
    from settings import (
        FIELD_LABELS,
        HTML_TEMPLATE_FILE,
        ROUTINES_FILE,
    )

from measurement_config import validate_measurement_config, canonical_config
from line_planner import POINT_TO_POINT, line_geometry
from read_routines import read_routines_file


# Read the static shell once; each response substitutes only dynamic controls.
HTML_TEMPLATE = HTML_TEMPLATE_FILE.read_text(encoding="utf-8")


def display_value(value: Any) -> str:
    """Convert a JSON leaf value to its editable representation."""

    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def display_field_value(key: str, value: Any) -> str:
    """Return a field value in its operator-facing unit."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        shown = f"{value:.2f}".rstrip("0").rstrip(".")
        return "0" if shown == "-0" else shown
    return display_value(value)


def numeric_display_attributes(key: str, value: Any) -> str:
    """Keep exact numeric inputs available independently of their shown text."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    raw = html.escape(str(value), quote=True)
    shown = html.escape(display_field_value(key, value), quote=True)
    return f' data-raw-value="{raw}" data-display-value="{shown}" data-initial-raw-value="{raw}"'


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
    """Parse a form field in the same units used by the config file."""

    if key == "hold_duration":
        return float(text)
    return parse_value(text, template)


def edited_config(
    defaults: dict[str, Any],
    fields: dict[str, list[str]],
    routines_data: dict | None = None,
) -> dict[str, Any]:
    """Build a typed configuration from submitted form fields."""

    defaults = canonical_config(defaults)
    config = deepcopy(defaults)
    method = POINT_TO_POINT
    parameter_templates = {
        "increment": 100.0,
        "number_of_measurements": 5,
        "x_start": 0.0,
        "x_end": 0.0,
        "offset_y": 0.0,
    }

    parameters = {}
    for key, fallback in parameter_templates.items():
        field_name = f"line.{key}"
        if field_name not in fields:
            raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
        template = fallback
        try:
            parameters[key] = parse_field_value(key, fields[field_name][0], template)
        except ValueError as error:
            raise ValueError(f"{FIELD_LABELS.get(key, key)}: {error}") from error
    config["line"] = parameters
    parameters["auto_fit"] = parse_value(fields.get("line.auto_fit", ["true"])[0], True)
    if parameters["auto_fit"] and parameters["x_end"] <= parameters["x_start"]:
        raise ValueError("X End must be larger than X Start when Automatic Fit is enabled.")
    if method == "point_to_point":
        spacing_source = fields.get(
            "line.spacing_source", ["increment"]
        )[0]
        if spacing_source not in {"increment", "count"}:
            raise ValueError("Point-to-point spacing source is invalid.")
        config["line"].update(
            {
                "start_point": "p_start_l",
                "end_point": "p_end_l",
                "spacing_source": spacing_source,
            }
        )

    for section, values in defaults.items():
        if section in {"line", "obstacle"}:
            continue
        for key, template in values.items():
            if section == "measurement" and key in ("program_path", "simulation_program_path"):
                # This hidden deployment setting comes from current defaults,
                # never from a stale value submitted by an open browser tab.
                config[section][key] = template
                continue
            field_name = f"{section}.{key}"
            if field_name not in fields:
                raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
            try:
                config[section][key] = parse_field_value(key, fields[field_name][0], template)
            except ValueError as error:
                label = FIELD_LABELS.get(key, key.replace("_", " ").title())
                raise ValueError(f"{label}: {error}") from error

    obstacle_enabled = fields.get("obstacle.enabled") == ["true"]
    obstacle = {}
    selected_obstacle_keys = ["start", "end"] if obstacle_enabled else []

    for key in selected_obstacle_keys:
        field_name = f"obstacle.{key}"
        if field_name not in fields:
            raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
        try:
            obstacle[key] = parse_field_value(
                key, fields[field_name][0], 0.0
            )
        except ValueError as error:
            label = FIELD_LABELS.get(key, key.replace("_", " ").title())
            raise ValueError(f"{label}: {error}") from error

    if obstacle:
        config["obstacle"] = obstacle
    else:
        config.pop("obstacle", None)

    if method == POINT_TO_POINT:
        if routines_data is None:
            routines_data = read_routines_file(ROUTINES_FILE)
        geometry = line_geometry(config, routines_data)
        config["line"]["number_of_measurements"] = geometry[
            "number_of_measurements"
        ]
        config["line"]["increment"] = geometry["increment"]
        config["line"]["x_end"] = geometry["x_end"]
    validate_config(config, routines_data)
    return config


def validate_config(config: dict[str, Any], routines_data: dict | None = None) -> None:
    """Reject values that would make motion planning invalid or unsafe."""

    if routines_data is None:
        routines_data = read_routines_file(ROUTINES_FILE)
    validate_measurement_config(config, routines_data)
    if not config["measurement"]["program_path"].strip():
        raise ValueError("Robot program path cannot be empty.")


def form_html(
    config: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> str:
    """Return the complete launcher page."""

    config = canonical_config(config)
    if defaults is None:
        defaults = config
    else:
        defaults = canonical_config(defaults)
    optional_defaults = {
        "obstacle": {
            "start": 0.0,
            "end": 0.0,
        },
    }

    def current_value(section: str, key: str) -> Any:
        section_values = config.get(section) or {}
        if key in section_values:
            return section_values[key]
        default_values = defaults.get(section) or optional_defaults.get(section) or {}
        return default_values[key]

    def value_text(section: str, key: str) -> str:
        return html.escape(
            display_field_value(key, current_value(section, key)), quote=True
        )

    def input_html(section: str, key: str, attributes: str = "required") -> str:
        name = html.escape(f"{section}.{key}", quote=True)
        label = html.escape(FIELD_LABELS.get(key, key.replace("_", " ").title()), quote=True)
        return (
            f'<input id="{name}" name="{name}" value="{value_text(section, key)}" '
            f'aria-label="{label}"{numeric_display_attributes(key, current_value(section, key))} {attributes}>'
        )

    hidden_controls = []
    for section, keys in {
        "measurement": ("program_path", "simulation_program_path", "simulation", "force_direction", "stop_method"),
    }.items():
        for key in keys:
            if key not in defaults.get(section, {}):
                continue
            hidden_controls.append(
                f'<input type="hidden" name="{section}.{key}" '
                f'value="{value_text(section, key)}">'
            )

    method = "point_to_point"
    parameters = config["line"]

    def line_input(key: str, value: Any, attributes: str = "required") -> str:
        name = f"line.{key}"
        label = html.escape(FIELD_LABELS.get(key, key.replace("_", " ").title()))
        shown = html.escape(display_field_value(key, value), quote=True)
        return (
            f'<input id="{name}" name="{name}" value="{shown}" '
            f'aria-label="{label}"{numeric_display_attributes(key, value)} {attributes}>'
        )

    point_values = {
        "increment": parameters.get("increment", 100.0),
        "number_of_measurements": parameters.get("number_of_measurements", 5),
        "spacing_source": parameters.get("spacing_source", "increment"),
        "x_start": parameters.get("x_start", parameters.get("offset_x", 0.0)),
        "x_end": parameters.get("x_end", 0.0),
        "offset_y": parameters.get("offset_y", 0.0),
    }
    hidden_controls.append(
        '<input id="line.line_length" type="hidden" value="0.000">'
    )
    hidden_controls.append(
        '<input id="line.high_low_distance" type="hidden" value="0.000">'
    )
    increment = line_input("increment", point_values["increment"])
    measurement_count = point_values["number_of_measurements"]
    hidden_controls.append(
        '<input id="spacing-source" type="hidden" '
        'name="line.spacing_source" '
        f'value="{html.escape(point_values["spacing_source"], quote=True)}">'
    )
    point_offset_attributes = "required"
    auto_fit_checked = " checked" if parameters.get("auto_fit", True) else ""
    sections = [
        '<fieldset><legend>Measurement Line</legend>'
        '<div class="parameter-row routine-file-row"><label for="routine-file">Routine File</label>'
        '<select id="routine-file" aria-label="Routine file used by the measurement"></select></div>'
        '<small id="point-method-note" hidden></small>'
        '<div class="toggle-row"><label class="option-toggle">'
        f'<input id="auto-fit" type="checkbox"{auto_fit_checked}>Automatic Fit</label></div>'
        '<div class="parameter-row double line-spacing-row">'
        f'<span>Step Size [mm] / Nb. Points</span>{increment}'
        f'<input id="measurement-count" name="line.number_of_measurements" type="number" min="1" step="1" value="{measurement_count}" aria-label="Nb. Points" required>'
        '</div>'
        '<div class="parameter-row double">'
        f'<span>X Start / X End [mm]</span>{line_input("x_start", point_values["x_start"], point_offset_attributes)}'
        f'{line_input("x_end", point_values["x_end"], point_offset_attributes)}</div>'
        '<div class="parameter-row single">'
        f'<label for="line.offset_y">Y Offset [mm]</label>{line_input("offset_y", point_values["offset_y"], point_offset_attributes)}</div>'
        '</fieldset>'
    ]

    obstacle = config.get("obstacle") or {}
    obstacle_checked = " checked" if "start" in obstacle and "end" in obstacle else ""
    start = input_html("obstacle", "start", 'data-optional-group="obstacle-position"')
    end = input_html("obstacle", "end", 'data-optional-group="obstacle-position"')
    sections.append(
        '<fieldset id="obstacle-fields"><legend>Obstacle</legend>'
        '<div class="toggle-row">'
        '<label class="option-toggle"><input id="obstacle-enabled" name="obstacle.enabled" type="checkbox" value="true"'
        f'{obstacle_checked}>Obstacle Exists</label></div>'
        '<div class="parameter-row double obstacle-position-row" data-optional-group="obstacle-position">'
        f'<span>Positions Start / End [mm]</span>{start}{end}</div>'
        '</fieldset>'
    )

    for key in ("type", "speed", "acceleration"):
        if key in defaults.get("motion", {}):
            hidden_controls.append(
                f'<input type="hidden" name="motion.{key}" '
                f'value="{value_text("motion", key)}">'
            )

    target = input_html("measurement", "target_force")
    maximum = input_html("measurement", "max_displacement")
    server_checked = " checked" if current_value("measurement", "stop_method") == "client_feedback" else ""
    simulation_checked = " checked" if current_value("measurement", "simulation") else ""
    measurement_controls = (
        '<div class="toggle-row">'
        '<label class="option-toggle"><input id="acquisition-server-enabled" '
        'name="acquisition.server_profile" type="checkbox" value="server"'
        f'{server_checked}>With RTM Program</label>'
        '<label class="option-toggle">'
        f'<input id="simulation-enabled" type="checkbox"{simulation_checked}>Simulation</label></div>'
        f'<div class="parameter-row single force-row"><label for="measurement.target_force">Target Force [N]</label>{target}</div>'
        '<div class="parameter-row single">'
        f'<label for="measurement.max_displacement">Maximum Displacement [mm]</label>{maximum}</div>'
    )
    for key, default_value in defaults["measurement"].items():
        if key in {
            "program_path",
            "simulation",
            "force_direction",
            "stop_method",
            "target_force",
            "simulation_program_path",
            "max_displacement",
        }:
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

    replacements = {
        "{{HIDDEN_CONTROLS}}": "".join(hidden_controls),
        "{{SECTIONS}}": "".join(sections),
    }
    page = HTML_TEMPLATE
    for placeholder, value in replacements.items():
        page = page.replace(placeholder, value)
    return page
