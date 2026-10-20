"""Execute the Script-node control flow with mocked robot primitives.

This checks branching and the register/voltage protocol, not robot dynamics or
the controller's URScript parser. The source uses a shared Python/URScript subset
apart from global declarations and explicit block terminators.
"""

from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "src/measurement/polyscope_scripts/apply_force.script"


def translated_script():
    lines = []
    depth = 0
    for source_line in SCRIPT.read_text(encoding="utf-8").splitlines():
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "end":
            depth -= 1
            continue
        if line.startswith(("else:", "elif ")):
            depth -= 1
        if line.startswith("global "):
            line = line[len("global "):]
        lines.append("    " * depth + line)
        if line.endswith(":"):
            depth += 1
        if depth < 0:
            raise AssertionError("Unbalanced URScript blocks")
    if depth != 0:
        raise AssertionError("Unbalanced URScript blocks")
    return compile("\n".join(lines), str(SCRIPT), "exec")


class RobotStub:
    def __init__(self, mode=0, simulation=False, ack_after=3, norm=10, z_force=10,
                 max_distance=1, travel_per_call=0, initial_ack=0):
        self.mode = mode
        self.simulation = simulation
        self.ack_after = ack_after
        self.norm = norm
        self.z_force = z_force
        self.max_distance = max_distance
        self.travel_per_call = travel_per_call
        self.initial_ack = initial_ack
        self.status = None
        self.hold_ticks = 0
        self.ticks = 0
        self.active = False
        self.force_calls = 0
        self.events = []

    def input_integer(self, register):
        if register == 47:
            return self.mode
        if register == 46:
            return int(self.simulation)
        if register == 42:
            if self.status != 1:
                return self.initial_ack
            return int(self.ack_after is not None and self.hold_ticks >= self.ack_after)
        raise AssertionError(register)

    def output_integer(self, register, value):
        assert register == 42
        self.status = value
        self.events.append(("status", value))

    def force_mode(self, *args):
        self.force_calls += 1
        self.active = True
        self.events.append(("force",))

    def end_force_mode(self):
        self.active = False
        self.events.append(("end_force",))

    def sync(self):
        self.ticks += 1
        if self.status == 1:
            self.hold_ticks += 1
        if self.ticks > 1000:
            raise AssertionError("Script failed to finish within the test budget")

    def movel(self, target, **kwargs):
        assert not self.active, "Return must happen after force mode stops"
        assert target == [0] * 6, "Return must use the captured start pose"
        self.events.append(("return",))

    def run(self):
        namespace = {
            "read_input_integer_register": self.input_integer,
            "read_input_float_register": lambda r: {43: self.max_distance, 44: 5, 45: 10}[r],
            "write_output_integer_register": self.output_integer,
            "set_tool_voltage": lambda value: self.events.append(("voltage", value)),
            "get_actual_tcp_pose": lambda: [0, 0, self.force_calls * self.travel_per_call, 0, 0, 0],
            "pose_inv": lambda pose: [-value for value in pose],
            "pose_trans": lambda a, b: [x + y for x, y in zip(a, b)],
            "zero_ftsensor": lambda: None,
            "sleep": lambda duration: None,
            "force_mode": self.force_mode,
            "force": lambda: self.norm,
            "get_tcp_force": lambda: [0, 0, self.z_force, 0, 0, 0],
            "get_steptime": lambda: 0.1,
            "sync": self.sync,
            "end_force_mode": self.end_force_mode,
            "stopl": lambda acceleration: None,
            "movel": self.movel,
        }
        exec(translated_script(), namespace)
        return namespace

    @property
    def statuses(self):
        return [event[1] for event in self.events if event[0] == "status"]


class ApplyForceScriptTests(unittest.TestCase):
    def test_time_mode_pulses_for_duration_and_ignores_acknowledgement(self):
        robot = RobotStub(mode=1, ack_after=None, initial_ack=1, z_force=0)
        result = robot.run()
        self.assertEqual(robot.statuses, [0, 1, 0])
        self.assertEqual([e for e in robot.events if e[0] == "voltage"],
                         [("voltage", 0), ("voltage", 12), ("voltage", 0), ("voltage", 0)])
        self.assertAlmostEqual(result["elapsed_time"], 0.5)
        self.assertIn(("return",), robot.events)

    def test_feedback_uses_absolute_z_and_waits_for_ack_without_voltage_changes(self):
        robot = RobotStub(norm=0, z_force=-10, ack_after=7)
        robot.run()
        self.assertEqual(robot.statuses, [0, 1, 0])
        self.assertEqual(robot.hold_ticks, 8)
        self.assertFalse(any(e[0] == "voltage" for e in robot.events))

    def test_feedback_times_out_then_returns(self):
        robot = RobotStub(ack_after=None)
        robot.run()
        self.assertEqual(robot.statuses, [0, 1, 3, 0])
        self.assertIn(("return",), robot.events)

    def test_approach_failure_does_not_trigger_acquisition(self):
        for mode in (0, 1):
            for distance_limited in (False, True):
                with self.subTest(mode=mode, distance_limited=distance_limited):
                    robot = RobotStub(mode=mode, norm=0, z_force=0,
                                      max_distance=0.01 if distance_limited else 1,
                                      travel_per_call=0.01 if distance_limited else 0)
                    robot.run()
                    self.assertEqual(robot.statuses, [0, 2, 0])
                    self.assertNotIn(("voltage", 12), robot.events)
                    self.assertIn(("return",), robot.events)

    def test_simulation_stops_force_before_acquisition_in_both_modes(self):
        for mode in (0, 1):
            for distance_limited in (False, True):
                with self.subTest(mode=mode, distance_limited=distance_limited):
                    robot = RobotStub(mode=mode, simulation=True, norm=0, z_force=0,
                                      max_distance=0.01 if distance_limited else 1,
                                      travel_per_call=0.01 if distance_limited else 0)
                    result = robot.run()
                    self.assertEqual(robot.statuses, [0, 1, 0])
                    stop = robot.events.index(("end_force",))
                    reached = robot.events.index(("status", 1))
                    self.assertLess(stop, reached)
                    self.assertNotIn(("force",), robot.events[stop + 1:])
                    self.assertFalse(result["contact_detected"])
                    if mode == 1:
                        self.assertIn(("voltage", 12), robot.events[reached + 1:])

    def test_invalid_modes_have_no_motion_or_voltage_side_effects(self):
        for mode in (-1, 2):
            with self.subTest(mode=mode):
                robot = RobotStub(mode=mode)
                robot.run()
                self.assertEqual(robot.events, [("status", 4)])


if __name__ == "__main__":
    unittest.main()
