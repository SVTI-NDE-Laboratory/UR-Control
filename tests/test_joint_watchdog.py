"""Joint activity drives the watchdog while arrival still requires settling."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/robot"))
from robot_move import wait_until_at_joint_target


class JointFeedback:
    def __init__(self, clock, joints, speed=lambda now: 0.0):
        self.clock = clock
        self.joints = joints
        self.speed = speed

    def getSafetyStatusBits(self):
        return 0

    def getActualQ(self):
        return self.joints(self.clock[0])

    def getActualQd(self):
        return [self.speed(self.clock[0])] * 6


class JointWatchdogTests(unittest.TestCase):
    def wait_for_target(self, joints, speed=lambda now: 0.0, timeout=6.0):
        clock = [0.0]
        receiver = JointFeedback(clock, joints, speed)

        def advance(seconds):
            clock[0] += seconds

        with patch("robot_move.time.monotonic", side_effect=lambda: clock[0]), patch("robot_move.time.sleep", side_effect=advance):
            result = wait_until_at_joint_target(receiver, [1.0] * 6, 0.005, timeout)
        return result, clock[0]

    def test_other_joints_move_while_largest_target_error_stays_constant(self):
        # Joint zero stays still beyond the startup timeout while joint five
        # moves in increments below the threshold that must accumulate.
        def joints(now):
            if now < 3.0:
                return [0.0] * 5 + [now * 0.01]
            return [1.0] * 6

        result, elapsed = self.wait_for_target(joints)
        self.assertEqual(result, [1.0] * 6)
        self.assertGreaterEqual(elapsed, 3.2)

    def test_no_joint_activity_triggers_start_timeout(self):
        with self.assertRaisesRegex(TimeoutError, "did not start"):
            self.wait_for_target(lambda now: [0.0] * 6)

    def test_standstill_after_movement_triggers_stall_timeout(self):
        with self.assertRaisesRegex(TimeoutError, "stopped making progress"):
            self.wait_for_target(lambda now: [0.0] * 5 + [min(now, 0.5) * 0.1])

    def test_arrival_requires_every_joint_and_low_speed_to_settle(self):
        result, elapsed = self.wait_for_target(
            lambda now: [1.0] * 5 + [min(now, 1.0)],
            speed=lambda now: 0.02 if now < 1.5 else 0.0)
        self.assertEqual(result, [1.0] * 6)
        self.assertGreaterEqual(elapsed, 1.7)


if __name__ == "__main__":
    unittest.main()
