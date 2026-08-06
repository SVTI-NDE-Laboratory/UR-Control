# Sandbox

Temporary scripts for isolated robot tests.

## force_approach_new.script

Launch:

```powershell
python Sandbox\launch_force_approach_new.py
```

The URScript currently contains:

```urscript
python_ip = "192.168.3.100"
python_port = 50001
```

So the PC must be reachable by the robot at `192.168.3.100`, and Windows Firewall
must allow inbound TCP on port `50001`.

## Manual URP Start

To start the URP manually on the tablet while Python only listens:

```powershell
python Sandbox\listen_force_approach_result.py
```

Then press Play on the robot tablet.

The listener uses the same protocol as the automatic sandbox launcher. It waits
for `CONTACT`, `NO_CONTACT`, `RELEASED`, or `TIMEOUT`, and sends `RELEASE` after
`CONTACT`.

If the robot does not connect:

1. Confirm `force_approach_new.script` contains `python_ip = "192.168.3.100"` and `python_port = 50001`.
2. Start the Python listener before pressing Play on the tablet.
3. Allow inbound TCP port `50001` in Windows Firewall.
4. Confirm the robot and PC are on the `192.168.3.x` network.

Local listener self-test:

```powershell
python Sandbox\test_listener_local.py
```

This only tests Python locally. It does not prove the robot can reach the PC, but
it confirms the port can be opened by Python.

Expected robot messages:

- `CONNECTED`: robot opened the socket before starting the force approach.
- `CONTACT`: force reached; robot is holding and waiting for `RELEASE`.
- `NO_CONTACT`: max travel reached before force.
- `RELEASED`: Python sent `RELEASE`; robot is leaving hold and returning.
- `TIMEOUT`: robot held force until its internal timeout.

The sandbox currently auto-sends `RELEASE` after a short simulated acquisition
delay. Set `AUTO_RELEASE = False` in `launch_force_approach_new.py` to release
manually from the terminal.

## Output Register Scan

To retry robot-written RTDE output registers:

```powershell
python Sandbox\test_output_registers.py
```

This sends no-motion URScript snippets like:

```urscript
write_output_integer_register(address, value)
write_output_float_register(address, value)
```

Then Python tries both lower and upper RTDE receive ranges and skips unsupported
addresses. Supported ranges vary by controller/recipe, so the output labels
changes as `lower:<address>` or `upper:<address>`.

If no values change, Python is not seeing robot-written output registers with
the current RTDE recipe/range setup.
