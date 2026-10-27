"""RTM Cobot Studio routes; reuse original configuration/measurement routes unchanged."""

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from .settings import ROUTINE_FILE, PROFILE
from .profile import read_object, resolve_path, select_profile, change_data_directory, display_path, application_directory
from .dialogs import choose_local_data, choose_routine_script
from .routine_setup import RoutineSelection, RoutineCreation, routine_directory, selected_routine, select_routine, create_routine, creation_defaults
from .control import ControlWorkers
from .browser_session import BrowserSessions
from .sessions import FolderSelection, MeasurementStartRequest, measurement_folder
from .saved_configuration import configuration_folders, read_saved_configuration
from .waypoint_routes import routine_transitions, waypoint_motion_options, waypoint_motion_limits
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from webapp import server as legacy
from read_routines import read_routines_file, get_waypoint, get_routine

DIRECTORY = Path(__file__).parent
workers = ControlWorkers()
legacy.state.workers = workers
legacy.state.set_routine_file(ROUTINE_FILE)
# Also configure already-imported legacy modules (e.g. embedded/test hosts).
from webapp import launcher as legacy_launcher, worker_manager as legacy_workers
import measurement_config
legacy.SERVER_CONFIG_FILE = PROFILE.paths["measurement_defaults"]
legacy.TEMP_CONFIG_FILE = PROFILE.data_dir / "runtime/config_tmp.json"
legacy.state.output_directory = PROFILE.paths["results_directory"]
legacy_launcher.ROBOT_IP = legacy_workers.ROBOT_IP = PROFILE.values["robot_ip"]
measurement_config.DEFAULT_CONFIG_FILE = PROFILE.paths["measurement_defaults"]
@asynccontextmanager
async def lifespan(app):
    async def browser_closed():
        # Serialize shutdown against commands that can start another worker.
        async with mutation_lock:
            await asyncio.to_thread(close_app)

    sessions = BrowserSessions(browser_closed)
    app.state.browser_sessions = sessions
    try:
        yield
    finally:
        await sessions.stop()
        del app.state.browser_sessions
        if workers.snapshot()["running"]:
            try:
                await asyncio.to_thread(workers.stop, "RTM Cobot Studio shutdown")
            except RuntimeError:
                pass


api = FastAPI(title="RTM Cobot Studio", lifespan=lifespan)
mutation_lock = asyncio.Lock()


@api.middleware("http")
async def serialize_changes(request, call_next):
    """Also cover legacy preflight: no manual command can start during it."""
    if request.method == "POST":
        async with mutation_lock:
            sessions = getattr(api.state, "browser_sessions", None)
            if sessions is not None and sessions.closing and request.url.path != "/api/close":
                return JSONResponse({"detail": "The application is closing."}, status_code=409)
            return await call_next(request)
    return await call_next(request)


@api.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/manual")


@api.get("/api/browser-session")
async def browser_session(request: Request):
    """A persistent connection follows the tab even while it is in the background."""
    sessions = request.app.state.browser_sessions
    if sessions.closing:
        return HTMLResponse(status_code=204)

    async def events():
        token = sessions.connect()
        try:
            yield "retry: 1000\ndata: connected\n\n"
            while not await request.is_disconnected():
                host = getattr(api.state, "uvicorn_server", None)
                if sessions.closing or (host is not None and host.should_exit):
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
        finally:
            sessions.disconnect(token)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@api.get("/manual", response_class=HTMLResponse)
@api.get("/flexible", response_class=HTMLResponse)
@api.get("/automatic", response_class=HTMLResponse)
@api.get("/settings", response_class=HTMLResponse)
def shell(request: Request):
    worker = workers.snapshot()
    locked_path = {"flexible": "/flexible", "measurement": "/automatic"}.get(worker["kind"]) if worker["running"] else None
    if locked_path and request.url.path != locked_path:
        return RedirectResponse(locked_path, status_code=303)
    return (DIRECTORY / "index.html").read_text(encoding="utf-8")


@api.get("/configuration", response_class=HTMLResponse)
def configuration(defaults: bool = False, method: str = "point_to_point", server_profile: str | None = None):
    page = legacy.configuration_page(defaults, method, server_profile)
    preserve = legacy.state.get_config() is not None and not defaults
    page = page.replace('<form id="config-form">', f'<form id="config-form" data-preserve-line="{str(preserve).lower()}">')
    page = page.replace('id="load-configuration" type="button" hidden', 'id="load-configuration" type="button"')
    page = page.replace("<title>UR15 Control</title>", "<title>RTM Cobot Studio</title>")
    # Adapt only WebApp2's copy of the shared form; the original app keeps its UI.
    page = page.replace("</head>", '<link rel="stylesheet" href="/v2-static/dialogs.css">'
                        '<script src="/v2-static/dialogs.js" defer></script></head>')
    page = re.sub(r'<fieldset class="run-measurement-fieldset">.*?</fieldset>',
                  lambda _: (DIRECTORY / "automatic_run.html").read_text(encoding="utf-8"), page, count=1, flags=re.S)
    page = re.sub(r'<div class="summary-tools">.*?</svg>',
                  lambda _: (DIRECTORY / "automatic_visualization.html").read_text(encoding="utf-8"), page, count=1, flags=re.S)
    page = re.sub(r'<script>.*?</script>', '<script src="/v2-static/measurement_visualization.js" defer></script><script src="/v2-static/automatic.js" defer></script>',
                  page, count=1, flags=re.S)
    # Retain the tested original form/visualization, embedded in the new shell.
    routine_row = ('<div class="parameter-row routine-file-row"><label for="routine-file">Routine file</label>'
                   '<select id="routine-file" aria-label="Routine file used by the measurement"></select></div>')
    page = page.replace(routine_row, "")
    return page.replace(
        "</head>", '<link rel="stylesheet" href="/v2-static/automatic.css"><style>.app-header,#point-method-note{display:none} html{overflow:hidden} body{min-height:0;padding:0;background:transparent;display:flow-root} main{width:100%;min-height:0;margin:0;padding:0;box-shadow:none;background:transparent}</style></head>')


class SavedConfigurationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directory: str = Field(max_length=1000)


@api.get("/api/configuration/results")
def saved_configuration_folders(directory: str = ""):
    try:
        return configuration_folders(PROFILE.paths["results_directory"], directory)
    except (OSError, ValueError) as error:
        raise HTTPException(422, str(error)) from error


@api.post("/api/configuration/load")
def load_saved_configuration(request: SavedConfigurationSelection):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Wait for the current robot action to finish before loading a configuration.")
    try:
        routines = read_routines_file(ROUTINE_FILE)
        config = read_saved_configuration(PROFILE.paths["results_directory"], request.directory, routines)
        legacy.write_json_atomic(legacy.TEMP_CONFIG_FILE, measurement_config.configuration_file(config))
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(422, f"Could not load this configuration: {error}") from error
    legacy.state.set_loaded_defaults(config)
    legacy.state.set_config(config)
    return {"loaded": True, "directory": request.directory}


@api.get("/api/configuration/routine-files")
def routine_files():
    return {"files": [ROUTINE_FILE.name], "default": ROUTINE_FILE.name, "locked": True}


@api.post("/api/configuration/routine-file")
def routine_file():
    raise HTTPException(403, "The installation routine file is fixed in RTM Cobot Studio.")


@api.post("/api/measurement/start")
def start_measurement(request: MeasurementStartRequest):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Wait for the current robot action to finish.")
    config = legacy.state.get_config()
    if config is None:
        raise HTTPException(409, "Validate the configuration before starting a measurement.")
    results = PROFILE.paths["results_directory"].resolve()
    session_id, started_at = legacy.create_session_identity()
    name = session_id if request.automatic_folder_name else request.folder_name
    try:
        # Check before robot preflight, then reserve atomically before any writes.
        folder = measurement_folder(results, name)
        config["measurement"]["program_path"] = legacy.read_default_program_path()
        config["measurement"]["simulation_program_path"] = legacy.read_default_program_path(True)
        warning = legacy.line_scope_warning(legacy.line_geometry(config, read_routines_file(ROUTINE_FILE)))
        if warning and not request.outside_line_confirmed:
            raise HTTPException(409, warning)
        legacy.assert_safe_start_position(ROUTINE_FILE)
        results.mkdir(parents=True, exist_ok=True)
        folder.mkdir(exist_ok=False)
        legacy.write_json_atomic(folder / "session.json", {
            "session_id": session_id, "started_at": started_at,
            "automatic_session_folder": request.automatic_folder_name,
            "folder_name": name, "base_output_directory": str(results), "output_directory": str(folder)})
        worker = workers.start_measurement(config, folder, request.show_terminal, ROUTINE_FILE)
    except FileExistsError as error:
        raise HTTPException(409, f'The measurements folder "{name}" already exists. Choose a different name; existing results will not be overwritten.') from error
    except (OSError, RuntimeError, ValueError) as error:
        raise legacy.worker_error(error) from error
    legacy.state.set_session(session_id, started_at)
    return {"started": True, "worker": worker, "session_id": session_id,
            "folder_name": name, "output_directory": str(folder)}


@api.post("/api/measurement/folder")
def check_measurement_folder(request: FolderSelection):
    if request.automatic_folder_name:
        return {"available": True}
    try:
        measurement_folder(PROFILE.paths["results_directory"], request.folder_name)
    except FileExistsError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"available": True, "folder_name": request.folder_name}


@api.get("/api/measurement")
def measurement_status():
    data = legacy.measurement_status()
    worker = data["worker"]
    data["measurement_folder_name"] = (Path(worker["state_file"]).parent.name
                                       if worker["kind"] == "measurement" and worker["state_file"] else None)
    data["default_output_directory"] = str(PROFILE.paths["results_directory"])
    return data


class ProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_path: str = Field(min_length=1)


@api.get("/api/settings")
def installation_settings():
    selected = resolve_path(read_object(PROFILE.preferences_path)["configuration_path"], PROFILE.data_dir)
    saved_routine = selected_routine(PROFILE)
    return {"data_directory": str(PROFILE.data_dir),
            "preferences_path": str(PROFILE.preferences_path),
            "active_configuration_path": str(PROFILE.path),
            "configuration_path": str(selected),
            "restart_required": selected != PROFILE.path or application_directory() != PROFILE.data_dir or saved_routine != ROUTINE_FILE,
            "routine_filename": saved_routine.name,
            "routine_creation_defaults": creation_defaults(PROFILE),
            "robot_ip": PROFILE.values["robot_ip"],
            "paths": {name: str(path) for name, path in PROFILE.paths.items()},
            "display_paths": {"app_config": display_path(PROFILE.path, PROFILE.data_dir),
                              "measurement_defaults": display_path(PROFILE.paths["measurement_defaults"], PROFILE.data_dir),
                              "wall_coordinates": display_path(PROFILE.paths["wall_coordinates"], PROFILE.data_dir),
                              "results_directory": display_path(PROFILE.paths["results_directory"], PROFILE.data_dir),
                              "routine_directory": display_path(routine_directory(PROFILE), PROFILE.data_dir),
                              "routine_file": display_path(PROFILE.paths["routine_file"], PROFILE.data_dir)},
            "ui_defaults": PROFILE.values.get("ui_defaults", {})}


@api.get("/api/settings/routines")
def settings_routines():
    return {"files": sorted(path.name for path in routine_directory(PROFILE).glob("*.json") if path.is_file()),
            "selected": selected_routine(PROFILE).name}


@api.post("/api/settings/routines/select")
def settings_select_routine(request: RoutineSelection):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Finish or stop the current robot action before changing the routine file.")
    try:
        path = select_routine(PROFILE, request.filename)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(400, str(error)) from error
    legacy.state.clear_config()
    return {"filename": path.name, "restart_required": path != ROUTINE_FILE,
            "message": "Routine file saved. Close and relaunch RTM Cobot Studio to use it." if path != ROUTINE_FILE else "This routine file is already in use."}


@api.post("/api/settings/routines/create")
def settings_create_routine(request: RoutineCreation):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Finish or stop the current robot action before creating a routine file.")
    try:
        path = create_routine(PROFILE, request)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(400, str(error)) from error
    return {"filename": path.name, "message": f"Created {path.name}. Use Change file to select it."}


@api.post("/api/settings/routines/script")
def settings_choose_script():
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Finish or stop the current robot action before choosing a script.")
    try:
        path = choose_routine_script(PROFILE.paths["routine_scripts_directory"])
        if path is None:
            return {"cancelled": True}
        if path.suffix.lower() != ".script":
            raise ValueError("Choose a PolyScope .script file.")
        if path.stat().st_size > 5_000_000:
            raise ValueError("Choose a script smaller than 5 MB.")
        return {"cancelled": False, "filename": path.name, "script": path.read_text(encoding="utf-8-sig")}
    except (OSError, ValueError) as error:
        raise HTTPException(400, str(error)) from error


@api.post("/api/settings/local-data")
def select_local_data():
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Finish or stop the current robot action before changing the local data folder.")
    try:
        selected = choose_local_data()
        if selected is None:
            return {"cancelled": True}
        candidate = change_data_directory(PROFILE, selected)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(400, str(error)) from error
    return {"cancelled": False, "data_directory": str(candidate.data_dir),
            "restart_required": candidate.data_dir != PROFILE.data_dir,
            "message": "Local data folder saved. Close and relaunch RTM Cobot Studio to use it."
                       if candidate.data_dir != PROFILE.data_dir else "This local data folder is already in use."}


@api.post("/api/settings")
def save_installation_settings(request: ProfileSelection):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Finish or stop the current robot action before changing Settings.")
    try:
        candidate = select_profile(PROFILE, request.configuration_path)
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(400, str(error)) from error
    return {"configuration_path": str(candidate.path), "restart_required": True,
            "message": "Configuration validated and saved. Close and relaunch RTM Cobot Studio to apply it."}


class ManualRequest(BaseModel):
    """Use the CLI's units; reject non-finite numbers and unknown fields."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["waypoint", "routine"]
    waypoint: str = ""
    routine: str = ""
    motion: Literal["l", "j"] = "l"
    speed: float = Field(50, gt=0)
    acceleration: float = Field(100, gt=0)

    @model_validator(mode="after")
    def validate_action(self):
        data = read_routines_file(ROUTINE_FILE)
        if self.action == "waypoint":
            waypoint = get_waypoint(data, self.waypoint)
            if not waypoint_motion_options(self.waypoint, waypoint)["linear" if self.motion == "l" else "joint"]:
                raise ValueError("This waypoint does not allow the selected motion type.")
            # Bound manual motion by the selected routine file's taught maxima.
            limits = waypoint_motion_limits(data)[self.motion]
            speed_limit, acceleration_limit = limits["speed"], limits["acceleration"]
            if self.speed > speed_limit or self.acceleration > acceleration_limit:
                raise ValueError(f"Manual limits: speed <= {speed_limit}, acceleration <= {acceleration_limit}.")
        elif self.action == "routine":
            if not get_routine(data, self.routine)["steps"]:
                raise ValueError("Routine is empty.")
        return self


@api.get("/api/manual/options")
def options():
    data = read_routines_file(ROUTINE_FILE)
    preferred = ("Home", "p_start_h", "p_start_l", "p_end_h", "p_end_l")
    names = [name for name in preferred if name in data["waypoints"]]
    names.extend(name for name in data["waypoints"] if name not in preferred)
    return {"routine_file": ROUTINE_FILE.name,
            "motion_limits": waypoint_motion_limits(data),
            "waypoints": [{"name": name, **waypoint_motion_options(name, data["waypoints"][name])} for name in names],
            "transitions": routine_transitions(data),
            "routines": [{"name": routine["name"], "first": routine["steps"][0]["waypoint"] if routine["steps"] else None} for routine in data["routines"]]}


@api.post("/api/manual/start")
def start_manual(request: ManualRequest):
    try:
        return workers.start_manual(request.model_dump())
    except (OSError, RuntimeError) as error:
        raise HTTPException(409 if isinstance(error, RuntimeError) else 400, str(error)) from error


class WaypointConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_file: str
    proceed: bool


@api.post("/api/manual/confirm-waypoint")
def confirm_waypoint(request: WaypointConfirmation):
    try:
        return workers.confirm_waypoint(request.state_file, request.proceed)
    except (OSError, RuntimeError) as error:
        raise HTTPException(409 if isinstance(error, RuntimeError) else 400, str(error)) from error


def flexible_options_data():
    """Read the fixed frame and CLI motion limits without contacting the robot."""
    from .flexible_worker import flexible, plane_geometry
    geometry = plane_geometry(read_routines_file(ROUTINE_FILE))
    from wall_coordinates import wall_limits, wall_reference
    x_min, x_max, y_min, y_max = wall_limits(geometry["taught_length"])
    return {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max,
            "wall_coordinates": wall_reference(), "speed": flexible.LINEAR_SPEED, "acceleration": flexible.LINEAR_ACCELERATION}


class FlexibleRequest(BaseModel):
    """Local plane commands, validated before queuing and again in the worker."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["move", "force", "end"]
    x: float | None = None
    y: float | None = None
    force: float = Field(200, gt=0)
    settling_time: float = Field(1.5, ge=0)
    # Preserve the existing operator-facing local hold range.
    duration: float = Field(3, ge=0, le=8)
    simulation: bool = False
    outside_range_confirmed: bool = False

    @model_validator(mode="after")
    def validate_command(self):
        if self.action == "move":
            limits = flexible_options_data()
            if self.x is None or self.y is None:
                raise ValueError("Specify both X and Y in millimetres.")
            if (not limits["x_min"] <= self.x <= limits["x_max"] or not limits["y_min"] <= self.y <= limits["y_max"]) and not self.outside_range_confirmed:
                raise ValueError(f"X must be within {limits['x_min']:.3f}–{limits['x_max']:.3f} mm and Y within {limits['y_min']}–{limits['y_max']} mm.")
        return self


@api.get("/api/flexible/options")
def flexible_options():
    return flexible_options_data()


@api.post("/api/flexible/start")
def start_flexible():
    try:
        return workers.start_flexible()
    except (OSError, RuntimeError) as error:
        raise HTTPException(409 if isinstance(error, RuntimeError) else 400, str(error)) from error


@api.post("/api/flexible/command")
def flexible_command(request: FlexibleRequest):
    try:
        return workers.send_flexible(request.model_dump())
    except (OSError, RuntimeError) as error:
        raise HTTPException(409 if isinstance(error, RuntimeError) else 400, str(error)) from error


@api.get("/api/status")
def status():
    worker, program, feedback = workers.details()
    mode = program.get("mode", "idle")
    error = (program.get("message") or mode) if mode in {"error", "unsafe_start", "measurement_failed"} else None
    error = error or program.get("action_error") or feedback.get("feedback_error")
    if worker["running"]:
        if worker["kind"] == "flexible":
            general = "Flexible measurement: Ready" if mode == "waiting_for_command" else "Flexible measurement: Running"
        else:
            general = "Manual mode" if worker["kind"] == "manual" else "Measurements: Running"
    else:
        general = "Idle"
    return {"general": general, "worker": worker, "program_state": {**program, **feedback},
            "feedback": feedback, "error": error, "routine_file": ROUTINE_FILE.name}


@api.get("/api/measurement")
def measurement_status():
    """Retain the final automatic display after runtime files are removed."""
    result = legacy.measurement_status()
    worker, program, _ = workers.details()
    if worker["kind"] == "measurement" and result["program_state"].get("mode") != "configuration_error":
        result.update(worker=worker, program_state=program)
    return result


@api.post("/api/worker/stop")
def stop_worker():
    """Abort the current worker and stop the robot; End handles a normal return."""
    return legacy.stop_worker()


@api.post("/api/close")
def close_app():
    try:
        if workers.snapshot()["running"]:
            workers.stop("RTM Cobot Studio close")
    finally:
        # Worker termination and hardware-stop errors must not leave a hidden app running.
        server = getattr(api.state, "uvicorn_server", None)
        if server is not None:
            server.should_exit = True
    return {"closed": True}


# Mount only original endpoints that are still applicable.
replaced = {route.path for route in api.routes}
for route in legacy.api.routes:
    if getattr(route, "path", None) not in replaced:
        api.router.routes.append(route)
api.mount("/v2-static", StaticFiles(directory=DIRECTORY / "static"), name="v2-static")
