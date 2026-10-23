"""Check rotated force vectors and both release paths with mocked robot calls.

Pose operations here are rigid transforms restricted to rotations around Y,
which is sufficient for these fixtures. These checks do not run a UR controller.
"""

import math
import unittest

from test_apply_force_script import SCRIPT, RobotStub


REGISTER_SCRIPT = SCRIPT.with_name("apply_force_from_ur.script")
DIRECT_SCRIPT = SCRIPT.with_name("apply_force_from_ur_direct.script")


def rotate_y(vector, angle):
    x, y, z = vector
    return [math.cos(angle) * x + math.sin(angle) * z, y,
            -math.sin(angle) * x + math.cos(angle) * z]


def pose_trans_y(a, b):
    """Compose actual rigid transforms for fixtures with only Y rotation."""
    assert a[3] == a[5] == b[3] == b[5] == 0
    translation = rotate_y(b[:3], a[4])
    return [a[i] + translation[i] for i in range(3)] + [0, a[4] + b[4], 0]


def pose_inv_y(pose):
    assert pose[3] == pose[5] == 0
    return rotate_y([-v for v in pose[:3]], -pose[4]) + [0, -pose[4], 0]


class RotatedRobot(RobotStub):
    def __init__(self, wrench=(20, 0, 0, 0, 0, 0), angle=math.pi / 2,
                 current_angle=None, **kwargs):
        super().__init__(**kwargs)
        self.wrench = list(wrench)
        self.start_pose = [1, 2, 3, 0, angle, 0]
        self.current_angle = angle if current_angle is None else current_angle

    def pose(self):
        displacement = rotate_y([0, 0, self.force_calls * self.travel_per_call], self.start_pose[4])
        angle = self.current_angle if self.force_calls else self.start_pose[4]
        return [self.start_pose[i] + displacement[i] for i in range(3)] + [0, angle, 0]

    def force_mode(self, frame, selection, wrench, mode, limits):
        assert frame == self.start_pose
        assert selection == [0, 0, 1, 0, 0, 0]
        assert mode == 2
        super().force_mode(frame, selection, wrench, mode, limits)

    def movel(self, target, **kwargs):
        assert not self.active
        assert target == self.start_pose
        self.events.append(("return",))

    def run(self, script=REGISTER_SCRIPT):
        def no_registers(*args):
            raise AssertionError("Direct script must not access registers")

        overrides = {
            "get_actual_tcp_pose": self.pose,
            "get_tcp_force": lambda: self.wrench,
            "pose_trans": pose_trans_y,
            "pose_inv": pose_inv_y,
        }
        if script == DIRECT_SCRIPT:
            overrides.update({name: no_registers for name in (
                "read_input_integer_register", "read_input_float_register",
                "write_output_integer_register")})
        return super().run(script, overrides)


class URForceScriptTests(unittest.TestCase):
    def test_base_x_is_tool_z_when_tool_is_rotated(self):
        for sign in (-1, 1):
            with self.subTest(sign=sign):
                robot = RotatedRobot(wrench=(20 * sign, 0, 0, 0, 0, 0), ack_after=7)
                result = robot.run()
                self.assertEqual(robot.statuses, [0, 1, 0])
                self.assertAlmostEqual(result["measured_force_z_signed"], 20 * sign)
                self.assertAlmostEqual(result["measured_force_z"], 20)
                self.assertEqual(robot.hold_ticks, 8)

    def test_large_base_z_does_not_trigger_sideways_tool(self):
        robot = RotatedRobot(wrench=(0, 0, 100, 0, 0, 0), ack_after=None)
        result = robot.run()
        self.assertEqual(robot.statuses, [0, 2, 0])
        self.assertFalse(result["contact_detected"])
        self.assertIn(("return",), robot.events)

    def test_current_orientation_is_used_instead_of_start_orientation(self):
        robot = RotatedRobot(angle=0, current_angle=math.pi / 2)
        result = robot.run()
        self.assertTrue(result["contact_detected"])
        self.assertAlmostEqual(result["measured_force_z"], 20)

    def test_helper_rotates_force_and_torque_without_tcp_translation(self):
        robot = RotatedRobot(wrench=(20, 3, 4, 5, 6, 7))
        result = robot.run()
        transformed = result["get_tcp_force_tool"]()
        for actual, expected in zip(transformed, [-4, 3, 20, -7, 6, 5]):
            self.assertAlmostEqual(actual, expected)

    def test_register_hold_still_requires_acknowledgement(self):
        robot = RotatedRobot(ack_after=None)
        with self.assertRaisesRegex(AssertionError, "test budget"):
            robot.run()
        self.assertEqual(robot.statuses, [0, 1])
        self.assertNotIn(("return",), robot.events)

    def test_register_distance_failure_and_simulation_preserve_protocol(self):
        for simulation in (False, True):
            robot = RotatedRobot(wrench=(0, 0, 0, 0, 0, 0), simulation=simulation,
                                 max_distance=.01, travel_per_call=.02)
            result = robot.run()
            self.assertTrue(result["distance_reached"])
            self.assertEqual(robot.statuses, [0, 1 if simulation else 2, 0])
            self.assertIn(("return",), robot.events)
            if simulation:
                stop = robot.events.index(("end_force",))
                self.assertLess(stop, robot.events.index(("status", 1)))
                self.assertNotIn(("force",), robot.events[stop + 1:])

    def test_direct_runs_without_registers_and_holds_three_seconds_after_contact(self):
        robot = RotatedRobot(ack_after=None)
        result = robot.run(DIRECT_SCRIPT)
        self.assertTrue(result["force_reached"])
        self.assertGreaterEqual(result["hold_elapsed"], 3)
        self.assertLess(result["hold_elapsed"], 3.1)
        self.assertEqual(robot.force_calls, 1 + round(result["hold_elapsed"] / .1))
        self.assertIn(("return",), robot.events)
        self.assertEqual(robot.statuses, [])

    def test_direct_failed_approach_skips_hold_and_returns(self):
        for travel in (0, .02):
            robot = RotatedRobot(wrench=(0, 0, 100, 0, 0, 0), travel_per_call=travel)
            result = robot.run(DIRECT_SCRIPT)
            self.assertFalse(result["force_reached"])
            self.assertEqual(result["hold_elapsed"], 0)
            self.assertIn(("return",), robot.events)
            self.assertEqual(result["distance_reached"], travel > 0)


if __name__ == "__main__":
    unittest.main()
