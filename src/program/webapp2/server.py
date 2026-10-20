"""WebApp 2.0 routes; reuse original configuration/measurement routes unchanged."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from .settings import ROUTINE_FILE
from .control import ControlWorkers
from .waypoint_routes import routine_transitions, waypoint_motion_options
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from webapp import server as legacy
from webapp.models import MeasurementStartRequest
from read_routines import read_routines_file, get_waypoint, get_routine

DIRECTORY = Path(__file__).parent
workers = ControlWorkers()
legacy.state.workers = workers
legacy.state.set_routine_file(ROUTINE_FILE)
@asynccontextmanager
async def lifespan(app):
    yield
    if workers.snapshot()["running"]:
        try:
            workers.stop("WebApp 2.0 shutdown")
        except RuntimeError:
            pass


api = FastAPI(title="UR15 WebApp 2.0", lifespan=lifespan)
mutation_lock = asyncio.Lock()


@api.middleware("http")
async def serialize_changes(request, call_next):
    """Also cover legacy preflight: no manual command can start during it."""
    if request.method == "POST":
        async with mutation_lock:
            return await call_next(request)
    return await call_next(request)


@api.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/manual")


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
def configuration(defaults: bool = False, method: str = "point_to_point", server_profile: str = "server"):
    page = legacy.configuration_page(defaults, method, server_profile)
    # Retain the tested original form/visualization, embedded in the new shell.
    routine_row = ('<div class="parameter-row routine-file-row"><label for="routine-file">Routine File</label>'
                   '<select id="routine-file" aria-label="Routine file used by the measurement"></select></div>')
    page = page.replace(routine_row, "")
    # The original form still uses this object to load fixed geometry. Keep it
    # detached from the DOM rather than displaying a redundant selector.
    page = page.replace("const routineFileSelect = document.getElementById('routine-file');",
                        "const routineFileSelect = document.createElement('select');")
    return page.replace("routineFileSelect.disabled = controlsLocked;", "routineFileSelect.disabled = true;").replace(
        "</head>", '<style>.app-header,#point-method-note{display:none} html{overflow:hidden} body{min-height:0;padding:0;background:transparent;display:flow-root} main{width:100%;min-height:0;margin:0;padding:0;box-shadow:none;background:transparent}</style></head>')


@api.get("/api/configuration/routine-files")
def routine_files():
    return {"files": [ROUTINE_FILE.name], "default": ROUTINE_FILE.name, "locked": True}


@api.post("/api/configuration/routine-file")
def routine_file():
    raise HTTPException(403, "The installation routine file is fixed in WebApp 2.0.")


@api.post("/api/measurement/start")
def start_measurement(request: MeasurementStartRequest):
    if workers.snapshot()["running"]:
        raise HTTPException(409, "Wait for the current robot action to finish.")
    if legacy.state.get_config() is None:
        raise HTTPException(409, "Validate the configuration before starting a measurement.")
    return legacy.start_measurement(request)


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
            # Installation limits deliberately match the existing manual tools.
            speed_limit, acceleration_limit = (150, 150) if self.motion == "l" else (0.5, 0.5)
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
    return {"x_min": 0, "x_max": geometry["taught_length"], "y_min": flexible.MIN_MANUAL_Y,
            "y_max": flexible.MAX_MANUAL_Y, "speed": flexible.LINEAR_SPEED, "acceleration": flexible.LINEAR_ACCELERATION}


class FlexibleRequest(BaseModel):
    """Local plane commands, validated before queuing and again in the worker."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["move", "force", "end"]
    x: float | None = None
    y: float | None = None
    threshold: float = Field(140, gt=0)
    force: float = Field(160, gt=0)
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
                raise ValueError(f"X must be within 0–{limits['x_max']:.3f} mm and Y within {limits['y_min']}–{limits['y_max']} mm.")
        elif self.action == "force" and self.force < self.threshold:
            raise ValueError("Contact force must be at least the contact threshold.")
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


@api.post("/api/worker/stop")
def stop_worker():
    """Abort the current worker and stop the robot; End handles a normal return."""
    return legacy.stop_worker()


@api.post("/api/close")
def close_app():
    if workers.snapshot()["running"]:
        workers.stop("WebApp 2.0 close")
    server = getattr(api.state, "uvicorn_server", None)
    if server is not None:
        server.should_exit = True
    return {"closed": True}


# Mount only original endpoints that are still applicable. No original source
# files or endpoint implementations are modified.
replaced = {route.path for route in api.routes}
for route in legacy.api.routes:
    if getattr(route, "path", None) not in replaced:
        api.router.routes.append(route)
api.mount("/v2-static", StaticFiles(directory=DIRECTORY / "static"), name="v2-static")
