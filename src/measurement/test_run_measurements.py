import unittest
import sys
import types


sys.modules.setdefault(
    "rtde_io",
    types.SimpleNamespace(RTDEIOInterface=object),
)
sys.modules.setdefault(
    "rtde_receive",
    types.SimpleNamespace(RTDEReceiveInterface=object),
)

from run_measurements import next_successful_measurement_index


def config_with_obstacle() -> dict:
    return {
        "obstacle": {
            "start": 100.0,
            "end": 100.0,
        },
    }


class MeasurementStateIndexTests(unittest.TestCase):
    def test_success_advances_to_next_measurable_point(self):
        positions = [(0, 0.0), (1, 100.0), (2, 200.0)]

        self.assertEqual(
            next_successful_measurement_index(positions, 0, config_with_obstacle()),
            3,
        )

    def test_success_keeps_last_measurable_point(self):
        positions = [(0, 0.0), (1, 100.0), (2, 200.0)]

        self.assertEqual(
            next_successful_measurement_index(positions, 2, config_with_obstacle()),
            3,
        )


if __name__ == "__main__":
    unittest.main()
