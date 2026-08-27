"""Run only the measurement phase with parameters defined in this file.

Place the robot at the taught ``p_start_h`` waypoint, open this file in the
editor, and press Run. This example does not execute the start or end routine.
Review all constants below before use.
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
    assert_robot_running,
    assert_robot_safe,
    get_rtde_receive,
)
from run_measurements import MeasurementUnavailableError, run_measurements


# ---------------------------------------------------------------------------
# Edit the hard-coded parameters in this section.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
OUTPUT_DIR = PROJECT_ROOT / "src" / "program" / "config"

# Keep this enabled to prevent an accidental editor Run click from moving the
# robot immediately.
REQUIRE_OPERATOR_CONFIRMATION = True

# The robot must already be at p_start_h because this example intentionally
# skips the start routine. This is the allowed error for every joint, in rad.
START_JOINT_TOLERANCE = 0.005

# Linear distances are in millimetres, forces in newtons, acceleration is
# mm/s^2, and speed is mm/s. Direction vectors are expressed in the tool frame.
MEASUREMENT_CONFIG = {
    "line": {
        "method": "translation",
        "parameters": {
            "line_length": 400.0,
            "increment": 200.0,
            "direction_start_end": [-1.0, 0.0, 0.0],
            "high_low_distance": 10.0,
            "direction_high_low": [0.0, 0.0, 1.0],
        },
    },
    "motion": {
        "type": "l",
        "acceleration": 100.0,
        "speed": 100.0,
    },
    "measurement": {
        "program_path": "Benoit/apply_force.urp",
        "contact_threshold": 80.0,
        "holding_force": 100.0,
        "max_displacement": 40.0,
        "simulation": True,
    },
}


def write_json_atomic(path: Path, value: dict) -> None:
    """Write JSON without leaving a partially written output file."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def assert_at_measurement_start(rtde_receive, target_q: list[float]) -> None:
    """Prevent motion unless the robot is at the taught p_start_h joints."""

    assert_robot_safe(rtde_receive)
    actual_q = rtde_receive.getActualQ()
    if len(actual_q) != len(target_q):
        raise UnsafeStartPositionError(
            "Cannot verify p_start_h: actual and target joint vectors differ in length."
        )

    errors = [abs(actual - target) for actual, target in zip(actual_q, target_q)]
    maximum_error = max(errors)
    if maximum_error > START_JOINT_TOLERANCE:
        joint_number = errors.index(maximum_error) + 1
        raise UnsafeStartPositionError(
            "Unsafe measurement start prevented: robot is not at p_start_h. "
            f"Joint {joint_number} differs by {maximum_error:.4f} rad; allowed "
            f"difference is {START_JOINT_TOLERANCE:.4f} rad. Move the robot to "
            "p_start_h before running this example."
        )


def run() -> None:
    """Verify p_start_h, then execute only the measurement traversal."""

    routines_data = read_routines_file(ROUTINES_FILE)
    start_waypoint = get_waypoint(routines_data, "p_start_h")
    if "q" not in start_waypoint:
        raise ValueError("The p_start_h waypoint has no joint target for verification.")

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
                "Confirm the robot is at p_start_h, then press Enter to start "
                "measurements, or Ctrl+C to cancel."
            )

        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)
        write_state(state_file, {"mode": "checking_measurement_start"})
        assert_at_measurement_start(rtde_receive, start_waypoint["q"])
        print("Startup position verified: robot is at p_start_h.")

        write_state(state_file, {"mode": "measurements"})
        run_measurements(
            ROBOT_IP,
            rtde_receive,
            MEASUREMENT_CONFIG,
            state_file,
            routines_data,
        )
        print("Measurements completed. Robot is at the high end-of-line position.")

    except UnsafeStartPositionError as error:
        write_state(state_file, {"mode": "unsafe_start", "message": str(error)})
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(3)
    except MeasurementUnavailableError as error:
        # run_measurements has already returned safely to p_start_h and written
        # the failed point into state.json.
        print(f"\n{error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        # run_measurements sends a physical stop command before propagating
        # Ctrl+C. Before measurement begins, no robot motion has been started.
        write_state(state_file, {"mode": "stopped", "reason": "operator cancellation"})
        print("\nMeasurements cancelled; any active motion was stopped.")
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
