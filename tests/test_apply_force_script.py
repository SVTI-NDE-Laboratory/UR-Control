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
                 max_distance=1, travel_per_call=0, initial_ack=0, duration=0.5):
        self.mode = mode
        self.simulation = simulation
        self.ack_after = ack_after
        self.norm = norm
        self.z_force = z_force
        self.max_distance = max_distance
        self.travel_per_call = travel_per_call
        self.initial_ack = initial_ack
        self.duration = duration
        self.status = None
        self.hold_ticks = 0
        self.ticks = 0
        self.active = False
        self.force_calls = 0
        self.events = []

    def input_integer(self, register):
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
    def test_real_hold_ends_only_on_python_acknowledgement(self):
        robot = RobotStub(z_force=-10, ack_after=7)
        robot.run()
        self.assertEqual(robot.statuses, [0, 1, 0])
        self.assertEqual(robot.hold_ticks, 8)
        self.assertIn(("return",), robot.events)
        self.assertFalse(any(e[0] == "voltage" for e in robot.events))

    def test_hold_can_exceed_old_ten_second_limit(self):
        robot = RobotStub(ack_after=150)
        robot.run()
        self.assertEqual(robot.statuses, [0, 1, 0])
        self.assertEqual(robot.hold_ticks, 151)

    def test_without_acknowledgement_robot_keeps_holding(self):
        robot = RobotStub(ack_after=None)
        with self.assertRaisesRegex(AssertionError, "test budget"):
            robot.run()
        self.assertEqual(robot.statuses, [0, 1])
        self.assertNotIn(("return",), robot.events)

    def test_failed_approach_returns_without_waiting_for_acknowledgement(self):
        for limited in (False, True):
            robot = RobotStub(norm=0, z_force=0, ack_after=None,
                              max_distance=.01 if limited else 1,
                              travel_per_call=.01 if limited else 0)
            robot.run()
            self.assertEqual(robot.statuses, [0, 2, 0])
            self.assertIn(("return",), robot.events)

    def test_simulation_stops_force_then_waits_for_same_release(self):
        for limited in (False, True):
            robot = RobotStub(simulation=True, ack_after=7,
                              max_distance=.01 if limited else 1,
                              travel_per_call=.01 if limited else 0)
            result = robot.run()
            self.assertEqual(robot.statuses, [0, 1, 0])
            stop = robot.events.index(("end_force",))
            self.assertLess(stop, robot.events.index(("status", 1)))
            self.assertNotIn(("force",), robot.events[stop + 1:])
            self.assertFalse(result["contact_detected"])
            self.assertEqual(robot.hold_ticks, 8)


if __name__ == "__main__":
    unittest.main()
