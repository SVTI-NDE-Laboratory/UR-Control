# Data Acquisition Control Guide

This folder contains the TCP control server used by the measurement program to
coordinate with an external data-acquisition client.

For the byte-level wire contract, see [`server_protocol.md`](server_protocol.md). This file
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
| `server_control.py` | TCP server used by the robot measurement program |
| `server_state.py` | Shared ALIVE, ISREADY, GO, and STATE data between robot code and TCP threads |
| `config_server.json` | Host, port, and acquisition-control timeouts |
| `server_protocol.md` | Exact TCP request/response contract |
| `server_logging.py` | Mirrors terminal output into timestamped log files |

The current LabVIEW-style protocol is implemented in `server_control.py`.

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
Python replies true
external client records data
external client sends GO
Python replies ACK
Python releases the robot force hold
robot returns from force mode
program continues to the next point
```

If the robot is not currently holding force, `ISREADY` returns `false`.

## LabVIEW Tester Settings

Use these endpoint settings:

```text
IP:   127.0.0.1
Port: 5055
```

For the simple control commands, configure the tester to read the exact
response length:

| Command | Expected response | Bytes Empfang |
|---|---|---:|
| `ALIVE` | `OK` | 2 |
| `ISREADY` | `true` or `false` | 4 or 5 |
| `GO` | `ACK` | 3 |
| `STATE` | JSON state payload | first read 4-byte length, then payload |

`STATE` and non-trivial/error responses use `[4 Byte I32][Data]`: first read
the 4-byte length, then read exactly that many payload bytes.

## Testing Without Starting the Full Robot Program

From the project root, start the standalone acquisition server tester:

```powershell
python src\program\data_acquisition\server_tester.py
```

This starts the same TCP server implementation used by the real measurement
program, but it does not connect to RTDE, load a URP, or move the robot.

Optional startup values:

```powershell
python src\program\data_acquisition\server_tester.py `
  --host 127.0.0.1 `
  --port 5055 `
  --point 1 `
  --x 123.0 `
  --y 333.0 `
  --ready
```

The tester opens a small console:

```text
hold                 make ISREADY return true until the client sends GO
point <n>            set STATE Point
pos <x> <y>          set STATE X/Y in mm
moving <on|off>      set STATE Moving
error <text>         set STATE Error text
clear-error          set STATE Error back to ok
state                print the current fake state
quit                 stop the tester
```

Use `hold` before testing the normal acquisition sequence if you want
`ISREADY` to return `true`. When the client sends `GO`, the fake hold ends and
`ISREADY` returns `false` again.

For a minimal non-interactive server-only test, this older one-liner still
works:

```powershell
python -c "import sys; sys.path.insert(0, r'src\program'); from data_acquisition.server_control import AcquisitionControlServer; server=AcquisitionControlServer('127.0.0.1', 5055, 8.0); server.start(); print('TCP test server listening on 127.0.0.1:5055'); input('Press Enter to stop server...'); server.stop()"
```

Then connect with the LabVIEW tester and send commands.

Expected behavior while no robot measurement is running:

```text
ALIVE   -> OK
ISREADY -> false
GO      -> ACK
STATE   -> [4 Byte I32][JSON data]
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

## Response Framing

Simple replies are sent directly as `OK`, `true`, `false`, or `ACK`, so the client
can read the known byte count for each command.

Non-trivial replies are framed as `[4 Byte I32][Data]`. The I32 is a signed
32-bit integer in network byte order and gives the length of the following
UTF-8 payload bytes. The payload is only the response text, for example an
`ERR ...` message. There is no trailing `\n` or `\r\n`.

`STATE` uses that same framing and returns JSON:

```json
{"X":123.0,"Y":333.0,"Point":1,"Moving":false,"Error":"ok"}
```

`X` and `Y` are live TCP position in millimetres when the robot RTDE connection
is available. `Moving` is a JSON boolean, and `Error` is `"ok"` unless the
program or live RTDE read reports an error.

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

If `ISREADY` always returns `false`:

- this is expected during the standalone TCP test
- during a real run, it returns `true` only while the robot is actively holding
  force at a measurement point

If the tester waits forever:

- for `ALIVE`, read 2 bytes
- for `ISREADY`, read 4 bytes for `true` or 5 bytes for `false`
- for `GO`, read 3 bytes
- for `STATE` and non-trivial/error responses, read the first 4 bytes as the response
  length, then read exactly that many payload bytes
