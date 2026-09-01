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

from measurement_config import validate_measurement_config
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

    if isinstance(value, float):
        return f"{value:.3f}"
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
    """Parse a form field in the same units used by the config file."""

    return parse_value(text, template)


def edited_config(
    defaults: dict[str, Any],
    fields: dict[str, list[str]],
    routines_data: dict | None = None,
) -> dict[str, Any]:
    """Build a typed configuration from submitted form fields."""

    config = deepcopy(defaults)
    method = fields.get("line.method", ["point_to_point"])[0]
    if method != "point_to_point":
        raise ValueError("Measurement line method must be point to point.")
    parameter_templates = {
        "increment": 100.0,
        "number_of_measurements": 5,
        "x_start": 0.0,
        "x_end": 0.0,
        "offset_y": 0.0,
    }

    current_parameters = defaults.get("line", {}).get("parameters", {})
    parameters = {}
    for key, fallback in parameter_templates.items():
        field_name = f"line.parameters.{key}"
        if field_name not in fields:
            raise ValueError(f"Missing field: {FIELD_LABELS.get(key, key)}")
        template = current_parameters.get(key, fallback)
        try:
            parameters[key] = parse_field_value(key, fields[field_name][0], template)
        except ValueError as error:
            raise ValueError(f"{FIELD_LABELS.get(key, key)}: {error}") from error
    config["line"] = {"method": method, "parameters": parameters}
    if method == "point_to_point":
        spacing_source = fields.get(
            "line.parameters.spacing_source", ["increment"]
        )[0]
        if spacing_source not in {"increment", "count"}:
            raise ValueError("Point-to-point spacing source is invalid.")
        config["line"]["parameters"].update(
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
                key, fields[field_name][0], defaults.get("obstacle", {}).get(key, 0.0)
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
    if method == POINT_TO_POINT:
        if routines_data is None:
            routines_data = read_routines_file(ROUTINES_FILE)
        geometry = line_geometry(config, routines_data)
        config["line"]["parameters"]["number_of_measurements"] = geometry[
            "number_of_measurements"
        ]
        config["line"]["parameters"]["increment"] = geometry["increment"]
        config["line"]["parameters"]["x_end"] = geometry["x_end"]
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

    if defaults is None:
        defaults = config
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
            f'aria-label="{label}" {attributes}>'
        )

    hidden_controls = []
    for section, keys in {
        "measurement": ("program_path", "simulation", "force_direction", "data_server"),
    }.items():
        for key in keys:
            if key not in defaults.get(section, {}):
                continue
            hidden_controls.append(
                f'<input type="hidden" name="{section}.{key}" '
                f'value="{value_text(section, key)}">'
            )

    method = "point_to_point"
    parameters = config["line"].get("parameters", config["line"])

    def line_input(key: str, value: Any, attributes: str = "required") -> str:
        name = f"line.parameters.{key}"
        label = html.escape(FIELD_LABELS.get(key, key.replace("_", " ").title()))
        shown = html.escape(display_field_value(key, value), quote=True)
        return (
            f'<input id="{name}" name="{name}" value="{shown}" '
            f'aria-label="{label}" {attributes}>'
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
        '<input id="line.method" type="hidden" name="line.method" '
        'value="point_to_point">'
    )
    hidden_controls.append(
        '<input id="line.parameters.line_length" type="hidden" value="0.000">'
    )
    hidden_controls.append(
        '<input id="line.parameters.high_low_distance" type="hidden" value="0.000">'
    )
    increment = line_input("increment", point_values["increment"])
    measurement_count = point_values["number_of_measurements"]
    hidden_controls.append(
        '<input id="spacing-source" type="hidden" '
        'name="line.parameters.spacing_source" '
        f'value="{html.escape(point_values["spacing_source"], quote=True)}">'
    )
    point_offset_attributes = "required"
    sections = [
        '<fieldset><legend>Measurement Line</legend>'
        '<div class="parameter-row routine-file-row"><label for="routine-file">Routine File</label>'
        '<select id="routine-file" aria-label="Routine file used by the measurement"></select></div>'
        '<small id="point-method-note" class="muted">Fixed: p_start_l to p_end_l</small>'
        '<div class="parameter-row double line-spacing-row">'
        f'<span>Increment [mm] / # Measurements</span>{increment}'
        f'<input id="measurement-count" name="line.parameters.number_of_measurements" type="number" min="2" step="1" value="{measurement_count}" aria-label="Number of measurements" required>'
        '</div>'
        '<div class="parameter-row double">'
        f'<span>X Start / X End [mm]</span>{line_input("x_start", point_values["x_start"], point_offset_attributes)}'
        f'{line_input("x_end", point_values["x_end"], point_offset_attributes)}</div>'
        '<div class="parameter-row single">'
        f'<label for="line.parameters.offset_y">Y Offset [mm]</label>{line_input("offset_y", point_values["offset_y"], point_offset_attributes)}</div>'
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

    contact = input_html("measurement", "contact_threshold")
    holding = input_html("measurement", "holding_force")
    maximum = input_html("measurement", "max_displacement")
    server_checked = " checked" if current_value("measurement", "data_server") else ""
    measurement_controls = (
        '<div class="toggle-row">'
        '<label class="option-toggle"><input id="acquisition-server-enabled" '
        'name="acquisition.server_profile" type="checkbox" value="server"'
        f'{server_checked}>Measurement with server</label></div>'
        f'<div class="parameter-row double force-row"><span>Force Contact / Holding [N]</span>{contact}{holding}</div>'
        '<div class="parameter-row single">'
        f'<label for="measurement.max_displacement">Maximum Displacement [mm]</label>{maximum}</div>'
    )
    for key, default_value in defaults["measurement"].items():
        if key in {
            "program_path",
            "simulation",
            "force_direction",
            "data_server",
            "contact_threshold",
            "holding_force",
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
