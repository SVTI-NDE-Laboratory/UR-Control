"""Guarded simulation control flow; mocks do not model stopping dynamics."""

import math
import unittest
from unittest.mock import Mock

from test_apply_force_script import RobotStub, SCRIPT
from test_apply_force_from_ur_script import pose_inv_y, pose_trans_y


class MovingSimulation(RobotStub):
    def __init__(self, angle=0, settling=.5, guard_stage=None, stalled_stage=None,
                 wrench=(0, 0, 0, 0, 0, 0), **kwargs):
        super().__init__(max_distance=.01, **kwargs)
        self.start = [1, 2, 3, 0, angle, 0]
        self.pose = self.start.copy()
        self.settling = settling
        self.guard_stage = guard_stage
        self.stalled_stage = stalled_stage
        self.wrench = wrench
        self.namespace = {}
        self.positions = []
        self.reads = []
        self.ready_position = None
        self.release_ticks = None
        self.forbidden = Mock(side_effect=AssertionError('Simulation must not enter force mode or zero contact'))

    def speedl(self, velocity, acceleration, duration):
        self.assert_guard_clear()
        assert duration == .1
        assert acceleration == .1
        self.events.append(('speed', velocity.copy()))
        if self.namespace['stage'] != self.stalled_stage:
            self.pose = [self.pose[i] + velocity[i] * duration for i in range(6)]
        self.positions.append(self.pose.copy())
        self.sync()

    def assert_guard_clear(self):
        assert math.sqrt(sum(f*f for f in self.force()[:3])) < 40

    def force(self):
        if self.namespace.get('stage') == self.guard_stage:
            return [30, 30, 0, 0, 0, 0]  # Resultant exceeds 40 N, individual axes do not.
        return self.wrench

    def output_integer(self, register, value):
        super().output_integer(register, value)
        if value == 1:
            self.ready_position = self.pose.copy()

    def input_integer(self, register):
        value = super().input_integer(register)
        if value == 1 and self.release_ticks is None:
            self.release_ticks = self.hold_ticks
        return value

    def run(self):
        from test_apply_force_script import translated_script

        def read_float(register):
            self.reads.append(register)
            return {43: self.max_distance, 44: self.settling, 45: 200}[register]

        self.namespace.update({
            'read_input_integer_register': self.input_integer,
            'read_input_float_register': read_float,
            'write_output_integer_register': self.output_integer,
            'get_actual_tcp_pose': lambda: self.pose.copy(),
            'get_tcp_force': self.force,
            'pose_trans': pose_trans_y, 'pose_inv': pose_inv_y, 'sqrt': math.sqrt,
            'speedl': self.speedl, 'stopl': lambda a: self.events.append(('stop',)),
            'sync': self.sync, 'get_steptime': lambda: .1,
            **{name: self.forbidden for name in ('force_mode', 'end_force_mode', 'zero_ftsensor', 'movel')},
        })
        exec(translated_script(SCRIPT.with_name('apply_force_simulation.script')), self.namespace)
        self.forbidden.assert_not_called()
        return self.namespace


class SimulationScriptTests(unittest.TestCase):
    def test_travel_settle_release_and_return_in_starting_tool_frame(self):
        for angle in (0, math.pi / 2, -math.pi / 2):
            for settling in (0, .5, 2.5):
                with self.subTest(angle=angle, settling=settling):
                    robot = MovingSimulation(angle=angle, settling=settling, ack_after=4)
                    result = robot.run()
                    self.assertEqual(robot.statuses, [0, 1, 0])
                    self.assertEqual(robot.reads, [43, 44, 45])
                    ready = pose_trans_y(pose_inv_y(robot.start), robot.ready_position)
                    self.assertAlmostEqual(ready[2], .01, delta=.00002)
                    self.assertAlmostEqual(ready[0], 0, delta=1e-10)
                    for pose in robot.positions:
                        self.assertLessEqual(pose_trans_y(pose_inv_y(robot.start), pose)[2], .01 + 1e-10)
                    self.assertLess(math.dist(robot.pose[:3], robot.start[:3]), .00002)
                    self.assertEqual(robot.pose[3:], robot.start[3:])
                    self.assertGreaterEqual(result['settling_elapsed'], settling)
                    self.assertTrue(result['force_ready'])
                    self.assertTrue(result['force_reached'])
                    self.assertEqual(robot.release_ticks, 4)

    def test_force_guard_aborts_in_place_in_every_stage(self):
        for stage in range(4):
            with self.subTest(stage=stage):
                robot = MovingSimulation(guard_stage=stage)
                result = robot.run()
                self.assertEqual(robot.statuses[-1], 5)
                self.assertEqual(result['failure'], 5)
                self.assertFalse(result['force_ready'])
                self.assertEqual(robot.events[-2:], [('stop',), ('status', 5)])
                self.assertFalse(any(event[0] == 'speed' and event[1][2] < 0 for event in robot.events))
                if stage == 0:
                    self.assertEqual(robot.pose, robot.start)

    def test_exact_guard_threshold_stops_before_first_move(self):
        robot = MovingSimulation(wrench=(0, -40, 0, 0, 0, 0))
        robot.run()
        self.assertEqual(robot.statuses, [0, 5])
        self.assertEqual(robot.positions, [])

    def test_contact_mid_approach_stops_without_return(self):
        robot = MovingSimulation()
        initial_force = robot.force
        robot.force = lambda: [0, 0, 41, 0, 0, 0] if robot.pose[2] > 3.003 else initial_force()
        robot.run()
        self.assertEqual(robot.statuses, [0, 5])
        self.assertGreater(robot.pose[2], 3.003)
        self.assertLess(robot.pose[2], 3.01)

    def test_stalled_approach_or_return_latches_timeout(self):
        for stage in (0, 3):
            with self.subTest(stage=stage):
                robot = MovingSimulation(stalled_stage=stage)
                robot.run()
                self.assertEqual(robot.statuses[-1], 6)
                self.assertEqual(robot.events[-2:], [('stop',), ('status', 6)])

    def test_contact_during_return_stops_at_contact_position(self):
        robot = MovingSimulation()
        initial_force = robot.force
        robot.force = lambda: ([41, 0, 0, 0, 0, 0]
                              if robot.namespace.get('stage') == 3 and robot.pose[2] < 3.007
                              else initial_force())
        robot.run()
        self.assertEqual(robot.statuses, [0, 1, 5])
        self.assertGreater(robot.pose[2], 3.0)
        self.assertLess(robot.pose[2], 3.007)

    def test_waits_for_client_release_at_travel_endpoint(self):
        robot = MovingSimulation(ack_after=None)
        with self.assertRaisesRegex(AssertionError, 'test budget'):
            robot.run()
        self.assertEqual(robot.statuses, [0, 1])
        self.assertEqual(robot.pose, robot.ready_position)

    def test_invalid_settings_do_not_move(self):
        for key, value in (('max_distance', 0), ('settling', -1)):
            robot = MovingSimulation()
            setattr(robot, key, value)
            robot.run()
            self.assertEqual(robot.statuses, [0, 4])
            self.assertEqual(robot.positions, [])
