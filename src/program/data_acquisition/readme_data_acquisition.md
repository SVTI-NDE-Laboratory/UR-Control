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
| `server_state.py` | Shared ALIVE, START_FIRST, ISREADY, GO, and STATE data between robot code and TCP threads |
| `config_server.json` | Host, port, and acquisition-control timeouts |
| `server_protocol.md` | Exact TCP request/response contract |
| `server_logging.py` | Mirrors terminal output into timestamped log files |

The current LabVIEW-style protocol is implemented in `server_control.py`.
Tester programs live outside the runtime package under `tools/data_acquisition`.

## Normal Measurement Sequence

When `measurement.data_server` is enabled, the measurement command starts the
TCP control server before robot motion begins.

Sequence:

```text
Python starts TCP server on 127.0.0.1:5055
external client connects
external client sends ALIVE
Python replies ACK
robot startup position is verified at Home
external client sends START_FIRST
Python replies ACK
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

In server mode, robot motion is blocked until the external client has sent
`ALIVE` and then `START_FIRST`. MIRA mode keeps the local operator prompt
instead.

## LabVIEW Tester Settings

The LabVIEW tester bundle is stored at:

```text
tools/data_acquisition/bam-cobot-tcp-tester-release-lv2024
```

Use these endpoint settings:

```text
IP:   127.0.0.1
Port: 5055
```

For the simple control commands, configure the tester to read the exact
response length:

| Command | Expected response | Bytes Empfang |
|---|---|---:|
| `ALIVE` | `ACK` | 3 |
| `START_FIRST` | `ACK` | 3 |
| `ISREADY` | `T` or `F` | 1 |
| `GO` | `ACK` | 3 |
| `STATE` | JSON state payload | first read 4-byte length, then payload |

`STATE` and non-trivial/error responses use `[4 Byte I32][Data]`: first read
the 4-byte length, then read exactly that many payload bytes.

## Testing Without Starting the Full Robot Program

From the project root, start the standalone acquisition server tester:

```powershell
python tools\data_acquisition\server_tester.py
```

This starts the same TCP server implementation used by the real measurement
program, but it does not connect to RTDE, load a URP, or move the robot.

Optional startup values:

```powershell
python tools\data_acquisition\server_tester.py `
  --host 127.0.0.1 `
  --port 5055 `
  --point 1 `
  --x 123.0 `
  --y 333.0
```

The interactive tester follows the same startup gate as the real server-mode
measurement command. It waits for `ALIVE`, then waits for `START_FIRST`. After
`START_FIRST`, it publishes `STATE` with `Point:1`, `Moving:true`, and
`ISREADY:F`, then opens the console.

To simulate a full 20-point measurement run without the robot:

```powershell
python tools\data_acquisition\server_tester.py --auto
```

In auto mode, the tester exposes points `1` through `20`, moves along the X
axis, and spends about 3 seconds moving between points. At each point,
`ISREADY` returns `T` until the acquisition client sends `GO`.
While moving, `STATE` reports the next point index, interpolated `X`,
unchanged `Y`, and `Moving:true`.

In auto mode, the tester follows the same startup gate as the real measurement
command: it waits for `ALIVE`, then waits for `START_FIRST`, then starts point
1.

Useful auto-mode options:

```powershell
python tools\data_acquisition\server_tester.py `
  --auto `
  --points 20 `
  --move-seconds 3 `
  --x 0 `
  --y 0 `
  --x-step 10
```

The tester opens a small console:

```text
ready                make ISREADY return T until the client sends GO
next [n]             advance STATE Point by n, default 1
mode <name>          set raw STATE mode
point <n>            set STATE Point
pos <x> <y>          set STATE X/Y in mm
error <text>         set STATE Error text
clear-error          set STATE Error back to ok
state                print the current fake state
quit                 stop the tester
```

Use `ready` before testing the normal acquisition sequence if you want
`ISREADY` to return `T`. Manual mode has no timer: the fake ready window stays
open until the client sends `GO`, then `ISREADY` returns `F` again.

Use `next` to advance the fake point quickly. It also advances the fake X
position by `--x-step`, so `STATE` changes in the same direction as auto mode.

For a minimal non-interactive server-only test, this older one-liner still
works:

```powershell
python -c "import sys; sys.path.insert(0, r'src\program'); from data_acquisition.server_control import AcquisitionControlServer; server=AcquisitionControlServer('127.0.0.1', 5055, 8.0); server.start(); print('TCP test server listening on 127.0.0.1:5055'); input('Press Enter to stop server...'); server.stop()"
```

Then connect with the LabVIEW tester and send commands.

Expected behavior while no robot measurement is running:

```text
ALIVE   -> ACK
START_FIRST -> ACK
ISREADY -> F
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

Heartbeat noise is filtered from the operator log: `ALIVE` exchanges and bare
`ACK` responses are not printed. `STATE` is printed only when its JSON payload
has `"Moving":false`.

It prints when the client disconnects:

```text
Data acquisition client 127.0.0.1:59775: disconnected
```

In a real web-launched run these lines appear in the session `program.log`.

## Response Framing

Simple replies are sent directly as `ACK`, `T`, or `F`, so the client
can read the known byte count for each command.

Non-trivial replies are framed as `[4 Byte I32][Data]`. The I32 is a signed
32-bit integer in network byte order and gives the length of the following
UTF-8 payload bytes. The payload is only the response text, for example an
`ERR ...` message. There is no trailing `\n` or `\r\n`.

`STATE` uses that same framing and returns JSON:

```json
{"X":123.0,"Y":333.0,"Point":1,"Moving":false,"Error":"ok"}
```

`X` is the live TCP X position in millimetres when available. Until an X value
exists, `STATE` returns `-9999`. `Y` is the configured
`line.parameters.offset_y` value in millimetres. `Point` is the current or next
measurement index, including before the first force measurement starts.
`Moving` is the opposite of the force-hold ready flag: it is `false` while
`ISREADY` returns `T`, and `true` while `ISREADY` returns `F`. `Error` is
`"ok"` unless the program or live RTDE read reports an error.

## Important Timing

`ALIVE` must arrive before `client_ready_timeout`, otherwise startup fails.

In server mode, robot motion waits indefinitely for `START_FIRST` after the
Home startup check passes.

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

- for `ALIVE`, read 3 bytes
- for `START_FIRST`, read 3 bytes
- for `ISREADY`, read 1 byte for `T` or `F`
- for `GO`, read 3 bytes
- for `STATE` and non-trivial/error responses, read the first 4 bytes as the response
  length, then read exactly that many payload bytes
