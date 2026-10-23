"""Offline register, fixed-delay, and continuous-force lifecycle checks."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_apply_force_from_ur_script import RotatedRobot, pose_inv_y, pose_trans_y
from test_apply_force_script import RobotStub

SCRIPT = Path(__file__).parent / 'scripts' / 'apply_force_from_ur_settling.script'


class SettlingRobot(RotatedRobot):
    """Track controller time and allow force/displacement to change after entry."""

    def __init__(self, target_at=0, dip_after_target=False, distance_at=None, settling_time=1.5, **kwargs):
        super().__init__(angle=0, wrench=(0, 0, 0, 0, 0, 0), **kwargs)
        self.target_at = target_at
        self.dip_after_target = dip_after_target
        self.distance_at = distance_at
        self.ready_at = None
        self.commanded_forces = []
        self.settling_time = settling_time

    def run(self, script=SCRIPT):
        return RobotStub.run(self, script, {
            'get_actual_tcp_pose': self.pose,
            'get_tcp_force': lambda: self.wrench,
            'pose_inv': pose_inv_y,
            'pose_trans': pose_trans_y,
            'read_input_float_register': lambda register: {
                43: self.max_distance, 44: self.settling_time, 45: 10}[register],
        })

    def pose(self):
        pose = self.start_pose.copy()
        if self.distance_at is not None and self.ticks >= self.distance_at:
            pose[2] += self.max_distance + .001
        return pose

    def force_mode(self, frame, selection, wrench, mode, limits):
        self.commanded_forces.append(wrench)
        super().force_mode(frame, selection, wrench, mode, limits)

    def sync(self):
        super().sync()
        self.wrench[2] = 10 if self.ticks >= self.target_at else 6
        if self.dip_after_target and self.ticks > self.target_at:
            self.wrench[2] = 8

    def output_integer(self, register, value):
        if value == 1:
            self.ready_at = self.ticks * .1
            assert self.active
        super().output_integer(register, value)


class RegisterSettlingTests(unittest.TestCase):
    def test_one_force_entry_target_then_delay_then_python_release(self):
        robot = SettlingRobot(target_at=5, ack_after=7)
        result = robot.run(SCRIPT)
        self.assertEqual(robot.commanded_forces, [[0, 0, 10, 0, 0, 0]])
        self.assertEqual(robot.statuses, [0, 1, 0])
        self.assertAlmostEqual(robot.ready_at, 2.0)
        self.assertTrue(result['force_ready'])
        self.assertTrue(result['force_reached'])
        self.assertNotIn('contact_detected', result)
        self.assertGreaterEqual(result['settling_elapsed'], 1.5)
        self.assertEqual(robot.hold_ticks, 8)
        self.assertLess(robot.events.index(('end_force',)), robot.events.index(('return',)))

    def test_force_below_target_does_not_signal_readiness(self):
        robot = SettlingRobot(target_at=10000)
        result = robot.run(SCRIPT)
        self.assertEqual(robot.statuses, [0, 2, 0])
        self.assertFalse(result['force_ready'])
        self.assertFalse(result['force_reached'])
        self.assertTrue(result['approach_timed_out'])

    def test_settling_time_comes_from_register(self):
        for delay in (0, .5, 2.0):
            with self.subTest(delay=delay):
                robot = SettlingRobot(target_at=5, settling_time=delay)
                result = robot.run()
                self.assertEqual(result['settling_time'], delay)
                self.assertAlmostEqual(robot.ready_at, .5 + max(.1, delay))

    def test_state_messages_are_defined_by_index(self):
        result = SettlingRobot().run()
        message = result['force_state_message']
        self.assertEqual(message(0), 'Setting program variables')
        self.assertEqual(message(9), 'Cycle completed')
        self.assertEqual(len({message(index) for index in range(10)}), 10)
        self.assertEqual(result['state_message'], message(9))

    def test_force_dip_does_not_restart_fixed_delay(self):
        robot = SettlingRobot(target_at=5, dip_after_target=True)
        robot.run(SCRIPT)
        self.assertAlmostEqual(robot.ready_at, 2.0)

    def test_distance_limit_during_settling_or_measurement(self):
        for distance_at in (10, 25):
            with self.subTest(distance_at=distance_at):
                robot = SettlingRobot(target_at=1, distance_at=distance_at, ack_after=None)
                result = robot.run(SCRIPT)
                self.assertTrue(result['distance_reached'])
                self.assertTrue(result['force_reached'])
                self.assertEqual(result['force_ready'], distance_at == 25)
                self.assertIn(2, robot.statuses)
                self.assertEqual(robot.events[-1], ('status', 0))
                self.assertIn(('return',), robot.events)

    def test_only_release_integer_register_is_read(self):
        robot = SettlingRobot(target_at=1)
        original_read = robot.input_integer
        reads = []

        def read(register):
            reads.append(register)
            self.assertEqual(register, 42)
            return original_read(register)

        robot.input_integer = read
        robot.run(SCRIPT)
        self.assertTrue(reads)
        self.assertEqual(robot.statuses, [0, 1, 0])

    def test_no_release_keeps_force_active(self):
        robot = SettlingRobot(target_at=1, ack_after=None)
        with self.assertRaisesRegex(AssertionError, 'test budget'):
            robot.run(SCRIPT)
        self.assertTrue(robot.active)
        self.assertEqual(robot.statuses, [0, 1])
        self.assertNotIn(('return',), robot.events)


if __name__ == '__main__':
    unittest.main()
