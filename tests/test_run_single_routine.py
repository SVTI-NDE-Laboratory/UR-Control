import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = PROJECT_ROOT / "tools" / "robot"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
for folder in [TOOL_DIR, ROBOT_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from robot_connection import UnsafeStartPositionError
from run_single_routine import assert_at_routine_first_waypoint


class FakeRtdeReceive:
    def __init__(self, actual_q: list[float]):
        self.actual_q = actual_q

    def getActualQ(self) -> list[float]:
        return self.actual_q

    def getSafetyStatusBits(self) -> int:
        return 0


def routine_data() -> dict:
    return {
        "waypoints": {
            "first": {"q": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]},
            "second": {"q": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]},
        },
        "routines": [
            {
                "name": "example",
                "steps": [
                    {"waypoint": "first", "motion": {"type": "j"}},
                    {"waypoint": "second", "motion": {"type": "j"}},
                ],
            }
        ],
    }


class RoutineFirstWaypointTests(unittest.TestCase):
    def test_accepts_robot_at_first_waypoint(self):
        first = routine_data()["waypoints"]["first"]["q"]

        waypoint_name = assert_at_routine_first_waypoint(
            FakeRtdeReceive(first),
            routine_data(),
            "example",
            0.01,
        )

        self.assertEqual(waypoint_name, "first")

    def test_rejects_robot_too_far_from_first_waypoint(self):
        actual_q = [0.0, 0.1, 0.2, 0.3, 0.4, 0.55]

        with self.assertRaisesRegex(UnsafeStartPositionError, "first waypoint"):
            assert_at_routine_first_waypoint(
                FakeRtdeReceive(actual_q),
                routine_data(),
                "example",
                0.01,
            )


if __name__ == "__main__":
    unittest.main()
