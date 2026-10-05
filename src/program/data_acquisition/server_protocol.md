# Data Acquisition Control Protocol

This protocol connects the external data-acquisition client to the main robot
program. The main robot program is the TCP server.

## Endpoint

The server listens on the host and port from:

```text
src/program/data_acquisition/config_server.json
```

Current default:

```text
127.0.0.1:5055
```

## Connection Model

The client may either:

- open one TCP connection and keep it open for repeated commands, or
- open a new TCP connection for each command.

The server logs these events locally:

- client connected
- message received
- response sent
- client disconnected

During a web-launched measurement run, these log lines are also written to the
session `program.log`.

## Request Format

Commands are ASCII text. The client may send plain-text commands directly. LF
termination is also accepted:

```text
\n
```

Accepted plain-text commands:

```text
ALIVE
START_FIRST
ISREADY
GO
STATE
```

JSON requests are also accepted for compatibility:

```json
{"message": "ALIVE"}
```

The command name is handled case-insensitively.

## Simple Fixed Responses

The simple control responses are sent as bare ASCII payloads with known byte
lengths. They do not include `\n`, `\r\n`, or a length prefix.

| Request | Response | Bytes to read | Meaning |
|---|---|---:|---|
| `ALIVE` | `ACK` | 3 | Client is present and startup may continue |
| `START_FIRST` | `ACK` | 3 | Client permits the first robot routine to start |
| `ISREADY` | `T` | 1 | Robot is holding force and data can be acquired |
| `ISREADY` | `F` | 1 | Robot is not ready for acquisition |
| `GO` | `ACK` | 3 | Server received the release/acquisition-complete command |

Raw response examples:

```text
ALIVE   -> b'ACK'
START_FIRST -> b'ACK'
ISREADY -> b'T' or b'F'
GO      -> b'ACK'
```

## Extended Responses

Non-trivial responses, including `STATE` and error messages, are sent as:

```text
[4 Byte I32][Data]
```

The first 4 bytes are a signed 32-bit integer in network byte order
(big-endian). This value is the byte length of the following UTF-8 response
payload. The payload does not include `\n` or `\r\n`.

Example:

```text
BOGUS -> b'\x00\x00\x00\x17ERR unsupported_message'
```

## Command Behavior

### `ALIVE`

Use this as the startup and watchdog command.

Response:

```text
ACK
```

The first successful `ALIVE` marks the external client as available. The main
measurement sequence waits for this before it moves on from acquisition startup.

### `START_FIRST`

Use this after the acquisition system and operator-side safety checks are ready
for robot motion to begin in server acquisition mode.

Response:

```text
ACK
```

For server acquisition runs, the robot program waits for this command just
before launching the first routine. MIRA acquisition runs keep the local
operator prompt instead.

### `ISREADY`

Use this to ask whether the robot has reached the force threshold and is
holding force for the current measurement point.

Response while force is held:

```json
T
```

Response otherwise:

```json
F
```

### `GO`

Send this after the acquisition system has recorded the data for the current
force-hold point.

Response:

```text
ACK
```

If the robot is currently waiting in a force-hold window, `GO` releases that
wait so Python can acknowledge robot input register 42 and continue. If no
measurement is waiting, `ACK` is still returned but no motion state changes.

### `STATE`

Use this to read the latest robot/program state.

Response:

```json
{"X":123.0,"Y":333.0,"Point":1,"Moving":false,"Error":"ok"}
```

The response is sent as `[4 Byte I32][Data]`. `X` is the live TCP X position in
millimetres when available. Until an X value exists, `STATE` returns `-9999`.
`Y` is the configured `line.parameters.offset_y` value in millimetres. `Point`
is the current or next measurement index, including before the first force
measurement starts.
`Moving` is a JSON boolean derived from the force-hold ready flag. It is the
opposite of `ISREADY`: when `ISREADY` returns `T`, `Moving` is `false`; when
`ISREADY` returns `F`, `Moving` is `true`. `Error` is `"ok"` or the current
error text.

## Timeouts

The active timeout values are configured in:

```text
src/program/data_acquisition/config_server.json
```

| Setting | Meaning |
|---|---|
| `client_ready_timeout` | Maximum startup wait for the first `ALIVE` |
| `go_timeout` | Maximum wait for `GO` after force is reached |

If `GO` arrives after `go_timeout`, the measurement fails and the robot program
enters its normal error/stop handling.
