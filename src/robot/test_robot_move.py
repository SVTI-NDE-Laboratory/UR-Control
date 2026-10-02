import math
import sys
import unittest
from pathlib import Path


ROBOT_DIR = Path(__file__).resolve().parent
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_move import relative_rotation_angle, tcp_target_errors


class TcpPoseErrorTests(unittest.TestCase):
    def test_relative_rotation_wraps_near_full_turn(self):
        angle = relative_rotation_angle([0.0, 0.0, 6.283160], [0.0, 0.0, 0.0])

        self.assertAlmostEqual(angle, (2.0 * math.pi) - 6.283160, places=12)

    def test_tcp_target_errors_uses_shortest_relative_rotation(self):
        actual_pose = [1.0, 2.0, 3.0, 0.0, 0.0, 6.283160]
        target_pose = [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]

        position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)

        self.assertEqual(position_error, 0.0)
        self.assertLess(rotation_error, 0.01)


if __name__ == "__main__":
    unittest.main()
