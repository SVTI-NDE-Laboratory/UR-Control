"""FastAPI routes for the single-page measurement control panel."""

import json
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

if __package__:
    from .config_form import edited_config, form_html
    from .launcher import assert_safe_start_position, choose_directory, write_json_atomic
    from .models import (
        ConfigurationSubmission,
        MeasurementStartRequest,
        RoutineFileSelection,
    )
    from .settings import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_SELECTED_ROUTINES_FILE,
        POINT_TO_POINT_CONFIG_FILE,
        ROUTINE_FILES_DIR,
        STATIC_DIR,
        TEMP_CONFIG_FILE,
        TRANSLATION_CONFIG_FILE,
    )
    from .worker_manager import WorkerBusyError, WorkerManager
else:
    from config_form import edited_config, form_html
    from launcher import assert_safe_start_position, choose_directory, write_json_atomic
    from models import (
        ConfigurationSubmission,
        MeasurementStartRequest,
        RoutineFileSelection,
    )
    from settings import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_SELECTED_ROUTINES_FILE,
        POINT_TO_POINT_CONFIG_FILE,
        ROUTINE_FILES_DIR,
        STATIC_DIR,
        TEMP_CONFIG_FILE,
        TRANSLATION_CONFIG_FILE,
    )
    from worker_manager import WorkerBusyError, WorkerManager

from measurement_plan import create_measurement_plan
from read_routines import get_waypoint, read_routines_file


class WebState:
    """Small synchronized state shared by FastAPI request threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.validated_config: dict[str, Any] | None = None
        self.output_directory = DEFAULT_OUTPUT_DIR
        self.selected_routine_file = DEFAULT_SELECTED_ROUTINES_FILE
        self.session_started_at: str | None = None
        self.session_id: str | None = None
        self.workers = WorkerManager()

    def get_config(self) -> dict[str, Any] | None:
        with self.lock:
            return deepcopy(self.validated_config)

    def set_config(self, config: dict[str, Any]) -> None:
        with self.lock:
            self.validated_config = deepcopy(config)

    def clear_config(self) -> None:
        with self.lock:
            self.validated_config = None

    def get_routine_file(self) -> Path:
        with self.lock:
            return self.selected_routine_file

    def set_routine_file(self, path: Path) -> None:
        with self.lock:
            if path != self.selected_routine_file:
                self.validated_config = None
            self.selected_routine_file = path

    def get_session(self) -> tuple[str | None, str | None]:
        with self.lock:
            return self.session_id, self.session_started_at

    def set_session(self, session_id: str, started_at: str) -> None:
        with self.lock:
            self.session_id = session_id
            self.session_started_at = started_at


state = WebState()
api = FastAPI(title="UR15 Cobot Control", docs_url="/api/docs")
api.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def read_json_if_available(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def default_config_path(method: str) -> Path:
    if method == "translation":
        return TRANSLATION_CONFIG_FILE
    if method == "point_to_point":
        return POINT_TO_POINT_CONFIG_FILE
    raise HTTPException(status_code=422, detail="Unknown measurement-line method.")


def load_default_config(method: str) -> dict[str, Any]:
    return json.loads(default_config_path(method).read_text(encoding="utf-8"))


def submitted_method(submission: ConfigurationSubmission) -> str:
    return submission.fields.get("line.method", [""])[0]


def routine_file_names() -> list[str]:
    return sorted(path.name for path in ROUTINE_FILES_DIR.glob("*.json"))


def resolve_routine_file(filename: str) -> Path:
    if filename not in routine_file_names():
        raise HTTPException(status_code=404, detail="Routine file not found.")
    return ROUTINE_FILES_DIR / filename


def worker_error(error: Exception) -> HTTPException:
    status = 409 if isinstance(error, WorkerBusyError) else 400
    return HTTPException(status_code=status, detail=str(error))


def create_session_identity() -> tuple[str, str]:
    """Return a fresh local-time ID and ISO timestamp for one program run."""

    started = datetime.now().astimezone()
    session_id = started.strftime("%Y-%m-%d_%H-%M-%S-%f")
    return session_id, started.isoformat(timespec="milliseconds")


@api.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/configuration")


@api.get("/configuration", response_class=HTMLResponse, include_in_schema=False)
def configuration_page(
    show_defaults: bool = Query(False, alias="defaults"),
    method: str = "point_to_point",
) -> str:
    if show_defaults:
        config = load_default_config(method)
    else:
        config = state.get_config() or load_default_config("point_to_point")
    defaults = load_default_config(config["line"]["method"])
    return form_html(config, defaults)


@api.get("/api/configuration")
def get_configuration() -> dict[str, Any]:
    config = state.get_config()
    return {
        "validated": config is not None,
        "config": config
        or load_default_config("point_to_point"),
    }


@api.get("/api/configuration/defaults")
def get_configuration_defaults() -> dict[str, Any]:
    return {
        "translation": load_default_config("translation"),
        "point_to_point": load_default_config("point_to_point"),
    }


@api.post("/api/configuration/validate")
def validate_configuration(
    submission: ConfigurationSubmission,
) -> dict[str, Any]:
    # A rejected edit must not leave an older configuration looking approved.
    state.clear_config()
    defaults = load_default_config(submitted_method(submission))
    routines_data = read_routines_file(state.get_routine_file())
    try:
        config = edited_config(defaults, submission.fields, routines_data)
        plan = create_measurement_plan(config, routines_data)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    write_json_atomic(TEMP_CONFIG_FILE, config)
    state.set_config(config)
    return {
        "validated": True,
        "message": "Configuration validated. The measurement is ready to start.",
        "config": config,
        "plan": plan,
    }


@api.post("/api/configuration/default")
def save_default_configuration(
    submission: ConfigurationSubmission,
) -> dict[str, Any]:
    """Validate the form and explicitly replace the shared default config."""

    state.clear_config()
    method = submitted_method(submission)
    defaults = load_default_config(method)
    routines_data = read_routines_file(state.get_routine_file())
    try:
        config = edited_config(defaults, submission.fields, routines_data)
        plan = create_measurement_plan(config, routines_data)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    write_json_atomic(default_config_path(method), config)
    write_json_atomic(TEMP_CONFIG_FILE, config)
    state.set_config(config)
    return {
        "validated": True,
        "message": "Configuration validated and saved as the new default.",
        "config": config,
        "plan": plan,
    }


@api.post("/api/configuration/reset")
def reset_configuration() -> dict[str, bool]:
    """Discard the in-memory approval so defaults can be reviewed again."""

    state.clear_config()
    return {"reset": True}


@api.get("/api/configuration/geometry")
def configuration_geometry() -> dict[str, Any]:
    """Return fixed point-to-point geometry from the selected routine file."""

    routine_file = state.get_routine_file()
    routines_data = read_routines_file(routine_file)
    try:
        start = get_waypoint(routines_data, "p_start_l")["p"]
        end = get_waypoint(routines_data, "p_end_l")["p"]
        safe = get_waypoint(routines_data, "p_start_h")["p"]
        line_length = sum(
            (end[index] - start[index]) ** 2 for index in range(3)
        ) ** 0.5
        safe_height = sum(
            (safe[index] - start[index]) ** 2 for index in range(3)
        ) ** 0.5
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "routine_file": routine_file.name,
        "start_point": "p_start_l",
        "end_point": "p_end_l",
        "safe_point": "p_start_h",
        "line_length": line_length,
        "safe_height": safe_height,
    }


@api.get("/api/select-directory")
def select_directory() -> dict[str, str | None]:
    try:
        selected = choose_directory()
    except OSError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {"path": str(selected) if selected else None}


@api.get("/api/measurement")
def measurement_status() -> dict[str, Any]:
    config = state.get_config()
    worker = state.workers.snapshot()
    state_file = Path(worker["state_file"]) if worker["state_file"] else None
    program_state = (
        read_json_if_available(state_file, {"mode": "not_started"})
        if state_file and worker["kind"] == "measurement"
        else {"mode": "not_started"}
    )
    plan = None
    if config is not None:
        try:
            plan_file = state_file.with_name("measurement_plan.json") if state_file else None
            plan = (
                read_json_if_available(plan_file, {})
                if plan_file and plan_file.exists()
                else create_measurement_plan(
                    config, read_routines_file(state.get_routine_file())
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            program_state = {"mode": "configuration_error", "message": str(error)}
    session_id, session_started_at = state.get_session()
    return {
        "validated": config is not None,
        "config": config,
        "plan": plan,
        "program_state": program_state,
        "worker": worker,
        "default_output_directory": str(state.output_directory),
        "session_id": session_id,
        "session_started_at": session_started_at,
        "routine_file": state.get_routine_file().name,
    }


@api.post("/api/measurement/start")
def start_measurement(request: MeasurementStartRequest) -> dict[str, Any]:
    if not request.operator_confirmed:
        raise HTTPException(status_code=400, detail="Safety confirmation is required.")
    if not request.output_directory.is_absolute():
        raise HTTPException(status_code=422, detail="The data folder must be absolute.")
    config = state.get_config()
    if config is None:
        raise HTTPException(
            status_code=409,
            detail="Validate the configuration before starting a measurement.",
        )
    base_output_directory = request.output_directory.resolve()
    routine_file = state.get_routine_file()
    try:
        assert_safe_start_position(routine_file)
        session_id, session_started_at = create_session_identity()
        output_directory = (
            base_output_directory / session_id
            if request.create_session_folder
            else base_output_directory
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            output_directory / "session.json",
            {
                "session_id": session_id,
                "started_at": session_started_at,
                "automatic_session_folder": request.create_session_folder,
                "base_output_directory": str(base_output_directory),
                "output_directory": str(output_directory),
            },
        )
        worker = state.workers.start_measurement(
            config, output_directory, request.show_terminal, routine_file
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise worker_error(error) from error
    state.set_session(session_id, session_started_at)
    state.output_directory = base_output_directory
    return {
        "started": True,
        "worker": worker,
        "session_id": session_id,
        "output_directory": str(output_directory),
    }


@api.post("/api/worker/stop")
def stop_worker() -> dict[str, Any]:
    try:
        worker = state.workers.stop("operator Stop button")
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"stopped": True, "worker": worker}


@api.get("/api/configuration/routine-files")
def configuration_routine_files() -> dict[str, Any]:
    files = routine_file_names()
    selected = state.get_routine_file().name
    default = selected if selected in files else (files[0] if files else None)
    return {"files": files, "default": default}


@api.post("/api/configuration/routine-file")
def select_routine_file(request: RoutineFileSelection) -> dict[str, Any]:
    path = resolve_routine_file(request.routine_file)
    # Read now so malformed files are rejected before becoming active.
    read_routines_file(path)
    state.set_routine_file(path)
    return {"selected": path.name}


@api.post("/api/close")
def close_app(background_tasks: BackgroundTasks) -> dict[str, bool]:
    worker = state.workers.snapshot()
    if worker["running"]:
        try:
            state.workers.stop("control panel Close app button")
        except RuntimeError:
            pass

    server = getattr(api.state, "uvicorn_server", None)
    if server is not None:
        background_tasks.add_task(setattr, server, "should_exit", True)
    return {"closed": True}
