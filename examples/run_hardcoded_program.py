"""Run the complete cobot sequence with parameters defined in this file.

Open this file in the editor and press Run. No command-line arguments or
browser configuration are required. Review the constants below before use.
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

from measurement_plan import write_measurement_plan
from measurement_state import write_state
from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
)
from run_measurements import run_measurements
from run_routine import run_routine


# ---------------------------------------------------------------------------
# Edit the hard-coded parameters in this section.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
OUTPUT_DIR = PROJECT_ROOT / "src" / "program" / "config"

# Retaining an operator confirmation prevents an accidental editor Run click
# from immediately moving the robot. Set this to False only if that is intended.
REQUIRE_OPERATOR_CONFIRMATION = True

# Routine motion is stored per step in routines_block.json.
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0
HOME_JOINT_TOLERANCE = 0.005

# Linear distances are in millimetres, forces in newtons, acceleration in
# mm/s^2, and speed in mm/s. Direction vectors are expressed in the tool frame.
MEASUREMENT_CONFIG = {
    "line": {
        "method": "translation",
        "parameters": {
            "line_length": 400.0,
            "increment": 100.0,
            "direction_start_end": [-1.0, 0.0, 0.0],
            "high_low_distance": 10.0,
            "direction_high_low": [0.0, 0.0, 1.0],
        },
    },
    "motion": {
        "type": "l",
        "acceleration": 50.0,
        "speed": 50.0,
    },
    "measurement": {
        "program_path": "Benoit/apply_force.urp",
        "contact_threshold": 30.0,
        "holding_force": 30.0,
        "max_displacement": 5.0,
        "simulation": True,
    },
}


def write_json_atomic(path: Path, value: dict) -> None:
    """Write JSON without leaving a partially written output file."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def run() -> None:
    """Run start routine, measurements, and end routine."""

    routines_data = read_routines_file(ROUTINES_FILE)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state_file = OUTPUT_DIR / "state.json"

    write_json_atomic(OUTPUT_DIR / "config_used.json", MEASUREMENT_CONFIG)
    write_measurement_plan(
        OUTPUT_DIR / "measurement_plan.json", MEASUREMENT_CONFIG, routines_data
    )

    rtde_receive = None
    try:
        if REQUIRE_OPERATOR_CONFIRMATION:
            input(
                "Press Enter to connect and start the hard-coded program, "
                "or Ctrl+C to cancel."
            )

        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)
        home = get_waypoint(routines_data, "Home")
        if "q" not in home:
            raise ValueError("The Home waypoint has no joint target for startup verification.")
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
    except KeyboardInterrupt:
        # run_routine/run_measurements send the physical stop command before
        # propagating Ctrl+C to this level.
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
