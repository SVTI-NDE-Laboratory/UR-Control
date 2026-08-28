# Data Acquisition Control Guide

This folder contains the TCP control server used by the measurement program to
coordinate with an external data-acquisition client.

For the byte-level wire contract, see [`protocol.md`](protocol.md). This file
explains how the pieces fit together during testing and during a real run.

## Roles

The main robot program is the TCP server. It listens for short commands from
the external client.

The external client is the data-acquisition side. In the current test setup
this is the LabVIEW-based **COBOT TCP TESTER - CLIENT** shown in the screenshot.

The server does not send unsolicited TCP messages. It only responds to client
commands. Connection status and received messages are printed locally by the
server and written to `program.log` during web-launched runs.

## Files

| File | Purpose |
|---|---|
| `control_server.py` | TCP server used by the robot measurement program |
| `state.py` | Shared ALIVE, ISREADY, and GO state between robot code and TCP threads |
| `config_server.json` | Host, port, and acquisition-control timeouts |
| `protocol.md` | Exact TCP request/response contract |
| `client.py` | Older JSON client helpers used by the previous acquisition-server design |
| `process.py` | Starts the legacy simulated acquisition server |
| `timestamped_logging.py` | Mirrors terminal output into timestamped log files |

The current LabVIEW-style protocol is implemented in `control_server.py`.

## Normal Measurement Sequence

When `measurement.data_server` is enabled, the measurement command starts the
TCP control server before robot motion begins.

Sequence:

```text
Python starts TCP server on 127.0.0.1:5055
external client connects
external client sends ALIVE
Python replies OK
measurement program continues startup
robot moves through the start routine
robot moves to a measurement point
robot runs the force program
robot reaches force threshold and holds force
external client sends ISREADY
Python replies T
external client records data
external client sends GO
Python replies ACK
Python releases the robot force hold
robot returns from force mode
program continues to the next point
```

If the robot is not currently holding force, `ISREADY` returns `F`.

## LabVIEW Tester Settings

Use these endpoint settings:

```text
IP:   127.0.0.1
Port: 5055
```

For the fixed short commands, configure the tester to read the exact response
length:

| Command | Expected response | Bytes Empfang |
|---|---|---:|
| `ALIVE` | `OK` | 2 |
| `ISREADY` | `T` or `F` | 1 |
| `GO` | `ACK` | 3 |

For extended/error messages, switch the tester receive mode to CRLF because
those responses end with `\r\n`.

## Testing Without Starting the Full Robot Program

From the project root, start only the TCP control server:

```powershell
python -c "import sys; sys.path.insert(0, r'src\program'); from data_acquisition.control_server import AcquisitionControlServer; server=AcquisitionControlServer('127.0.0.1', 5055, 8.0); server.start(); print('TCP test server listening on 127.0.0.1:5055'); input('Press Enter to stop server...'); server.stop()"
```

Then connect with the LabVIEW tester and send commands.

Expected behavior while no robot measurement is running:

```text
ALIVE   -> OK
ISREADY -> F
GO      -> ACK
```

This test does not connect to the robot, does not load a URP, and does not move
anything. It only checks the TCP server and the client communication settings.

## What The Server Logs

The server prints a line when the client connects:

```text
Data acquisition client 127.0.0.1:59775: connected
```

It prints each received command:

```text
Data acquisition client 127.0.0.1:59775: received ALIVE
```

It prints each response:

```text
Data acquisition client 127.0.0.1:59775: sent OK
```

It prints when the client disconnects:

```text
Data acquisition client 127.0.0.1:59775: disconnected
```

In a real web-launched run these lines appear in the session `program.log`.

## Why Short Responses Have No Terminator

The fixed control replies are intentionally only `OK`, `T`, `F`, and `ACK`.
They do not include `\n` or `\r\n`.

This matches the recommendation to minimize overhead for fixed short messages.
The LabVIEW tester should therefore read exactly 2, 1, or 3 bytes depending on
the command.

Longer or unexpected responses use CRLF so the tester can read until `\r\n`
when it is in CRLF mode.

## Important Timing

`ALIVE` must arrive before `client_ready_timeout`, otherwise startup fails.

`GO` must arrive before `go_timeout` after the robot has reached force and is
holding. If `GO` arrives too late, the measurement point is treated as failed
and the robot program enters normal stop/error handling.

Timeout defaults live in:

```text
src/program/data_acquisition/config_server.json
```

## Common Checks

If the tester cannot connect:

- confirm the server-only test command is running
- confirm the IP is `127.0.0.1`
- confirm the port is `5055`
- confirm no other process is already using port `5055`
- check Windows firewall only if testing from another machine

If `ISREADY` always returns `F`:

- this is expected during the standalone TCP test
- during a real run, it returns `T` only while the robot is actively holding
  force at a measurement point

If the tester waits forever:

- for `ALIVE`, read 2 bytes
- for `ISREADY`, read 1 byte
- for `GO`, read 3 bytes
- for error/extended text, use CRLF mode
