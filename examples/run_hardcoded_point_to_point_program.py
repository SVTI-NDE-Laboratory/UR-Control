"""Run the complete cobot sequence in point-to-point measurement mode.

The start routine moves from Home to ``p_start_h``. Measurement traversal then
moves to ``p_start_l`` and interpolates a three-dimensional line through
``p_end_l`` while retaining the orientation taught at ``p_start_l``. Review
all hard-coded parameters before running this file.
"""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from measurement_config import print_measurement_config_summary, validate_measurement_config
from measurement_plan import write_measurement_plan
from measurement_state import write_state
from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
)
from run_measurements import MeasurementUnavailableError, run_measurements
from run_routine import run_routine


# ---------------------------------------------------------------------------
# Review these hard-coded parameters before running the example.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = (
    ROUTINES_DIR / "routine_files" / "routines_pk-03-prism-a.json"
)
OUTPUT_DIR = PROJECT_ROOT / "src" / "program" / "config"

REQUIRE_OPERATOR_CONFIRMATION = True
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0
HOME_JOINT_TOLERANCE = 0.005

# number_of_measurements includes p_start_l and p_end_l. Candidate positions
# inside the obstacle interval are skipped, so the number of force cycles can
# be smaller than this configured value.
MEASUREMENT_CONFIG = {
    "line": {
        "method": "point_to_point",
        "parameters": {
            "start_point": "p_start_l",
            "end_point": "p_end_l",
            "number_of_measurements": 10,
        },
    },
    "motion": {
        "type": "l",
        "acceleration": 0.3,
        "speed": 0.3,
    },
    "measurement": {
        "program_path": "Benoit/apply_force.urp",
        "contact_threshold": 0.0,
        "holding_force": 0.0,
        "max_displacement": 0.001,
        # With nonzero forces this still performs a physical force approach.
        # Simulation only reports maximum displacement as a successful cycle.
        "simulation": False,
    },
}


def write_json_atomic(path: Path, value: dict) -> None:
    """Write JSON without leaving a partially written output file."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def run() -> None:
    """Run the diagonal start routine, measurements, and end routine."""

    routines_data = read_routines_file(ROUTINES_FILE)
    validate_measurement_config(MEASUREMENT_CONFIG, routines_data)
    print_measurement_config_summary(MEASUREMENT_CONFIG, routines_data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state_file = OUTPUT_DIR / "state.json"
    write_json_atomic(OUTPUT_DIR / "config_used.json", MEASUREMENT_CONFIG)
    write_measurement_plan(
        OUTPUT_DIR / "measurement_plan.json",
        MEASUREMENT_CONFIG,
        routines_data,
    )

    rtde_receive = None
    try:
        if REQUIRE_OPERATOR_CONFIRMATION:
            input(
                "Confirm the diagonal path, obstacle interval, and force "
                "parameters are safe, then press Enter to start, or Ctrl+C "
                "to cancel."
            )

        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)
        home = get_waypoint(routines_data, "Home")
        if "q" not in home:
            raise ValueError("The Home waypoint has no joint target.")

        write_state(state_file, {"mode": "checking_home"})
        assert_at_home(rtde_receive, home["q"], HOME_JOINT_TOLERANCE)
        print("Startup position verified: robot is at Home.")

        write_state(state_file, {"mode": "start_routine"})
        run_routine(
            "start",
            routines_data,
            ROBOT_IP,
            rtde_receive,
            JOINT_TOLERANCE,
            WAIT_TIMEOUT,
            False,
            True,
        )

        write_state(state_file, {"mode": "measurements"})
        run_measurements(
            ROBOT_IP,
            rtde_receive,
            MEASUREMENT_CONFIG,
            state_file,
            routines_data,
        )

        write_state(state_file, {"mode": "end_routine"})
        run_routine(
            "end",
            routines_data,
            ROBOT_IP,
            rtde_receive,
            JOINT_TOLERANCE,
            WAIT_TIMEOUT,
            False,
            True,
        )
        write_state(state_file, {"mode": "idle"})

    except UnsafeStartPositionError as error:
        write_state(state_file, {"mode": "unsafe_start", "message": str(error)})
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(3)
    except MeasurementUnavailableError as error:
        # run_measurements has already returned safely to p_start_h.
        print(f"\n{error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        # Lower-level routine and measurement functions request a robot stop.
        write_state(state_file, {"mode": "stopped", "reason": "operator cancellation"})
        print("\nProgram cancelled; any active motion was stopped.")
        raise SystemExit(130)
    except BaseException as error:
        write_state(
            state_file,
            {
                "mode": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )
        raise
    finally:
        if rtde_receive is not None:
            rtde_receive.disconnect()


if __name__ == "__main__":
    run()
