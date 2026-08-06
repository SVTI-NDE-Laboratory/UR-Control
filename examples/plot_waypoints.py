import sys
from pathlib import Path


ROUTINE_DATA_DIR = Path(__file__).resolve().parents[1] / "RoutineData"
if str(ROUTINE_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINE_DATA_DIR))

from extract_waypoints_from_script import extract_waypoints_from_script


SCRIPT = Path("Configuration/paths_Stefan.script")
WAYPOINTS = ["Home", "Tmp1", "Tmp2", "p_start_h"]


def main() -> None:
    waypoints = extract_waypoints_from_script(SCRIPT, WAYPOINTS)

    for name in WAYPOINTS:
        data = waypoints[name]

        if "p" not in data:
            print(f"{name}: no Cartesian position")
            continue

        x, y, z = data["p"][:3]
        print(f"{name}: x={x:.6f}, y={y:.6f}, z={z:.6f}")


if __name__ == "__main__":
    main()
