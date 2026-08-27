# Data Acquisition Server Communication Contract

This folder contains the current simulated data acquisition server. A separate
implementation can replace it as long as it follows the TCP protocol described
here.

The main robot program is the client. The data acquisition server is the TCP
server.

## Transport

- Host: configured in `src/program/data_acquisition/config_client.json`, currently
  `127.0.0.1`.
- Port: configured in `src/program/data_acquisition/config_client.json`, currently
  `5055`.
- Encoding: UTF-8.
- Framing: one JSON object followed by one newline character, `\n`.
- Connection model: one request and one response per TCP connection. The client
  closes the connection after reading the response.
- Protocol version: `1`.

The server should accept multiple short-lived connections and should be able to
answer heartbeat requests while an acquisition is in progress.

## Startup Handshake

Before the robot program connects to the robot, it verifies that the expected
acquisition service owns the configured port.

Request:

```json
{
  "message": "handshake",
  "client": "robot_main_program",
  "protocol_version": 1
}
```

Required response:

```json
{
  "message": "handshake_ack",
  "server": "data_acquisition_server",
  "protocol_version": 1
}
```

If this response is missing, malformed, or has a different protocol version,
the main program treats startup as failed.

## Heartbeat

After a successful handshake, the main program sends a heartbeat every
`heartbeat_interval` seconds. The current default is `2.0` seconds.

Request:

```json
{
  "message": "heartbeat",
  "client": "robot_main_program",
  "protocol_version": 1,
  "heartbeat_id": "unique-string",
  "sent_at": "2026-08-25T10:30:00.000+02:00"
}
```

Required response:

```json
{
  "message": "heartbeat_ack",
  "server": "data_acquisition_server",
  "protocol_version": 1,
  "heartbeat_id": "same unique-string",
  "received_at": "2026-08-25T10:30:00.010+02:00"
}
```

The main program logs a warning if a heartbeat fails. The data acquisition
server should use the heartbeat to detect that the main program is still alive.
A practical rule is to consider the main disconnected if no valid heartbeat is
received for at least three heartbeat intervals.

The server should not pause heartbeat handling while it is acquiring data.

## Acquisition Request

When the robot program needs one data record, it sends `acquire_data`.

Request:

```json
{
  "message": "acquire_data",
  "request_id": "unique-string",
  "measurement_index": 1,
  "line_position": 0.0
}
```

Only `message` and `request_id` are protocol-required. Other fields are
contextual metadata from the main program and may grow over time. The server
should preserve unknown request fields for logging/debugging and must not fail
only because an extra field appears. `line_position`, when present, is in
millimetres.

Required success response:

```json
{
  "message": "data_acquired",
  "request_id": "same unique-string",
  "completed_at": "2026-08-25T10:30:03.200+02:00"
}
```

The `request_id` must match the request. If it does not match, the main program
treats the acquisition as failed.

The current main-program request timeout is `request_timeout` in
`config_client.json`, currently `6.0` seconds. The server must answer before
this timeout expires.

## Error Responses

For unsupported or failed requests, return a JSON-line response instead of
closing the socket silently.

Recommended shape:

```json
{
  "message": "error",
  "request_id": "same unique-string if available",
  "error": "short_machine_readable_reason",
  "details": "human readable explanation"
}
```

The current main program treats any response other than the required success
response as a failed acquisition.

## Configuration Values Used By Main

`src/program/data_acquisition/config_client.json` currently contains:

```json
{
  "host": "127.0.0.1",
  "port": 5055,
  "startup_timeout": 5.0,
  "request_timeout": 6.0,
  "heartbeat_interval": 2.0,
  "heartbeat_timeout": 1.0
}
```

The reference server has its own `data_acquisition_server/config_server.json`
for local simulation settings. A production acquisition server does not need to
use that file.

## Current Reference Implementation

- `src/program/data_acquisition/client.py`: client helpers used by the main
  robot program.
- `src/program/data_acquisition/process.py`: local reference-server startup,
  shutdown, and handshake management.
- `src/program/data_acquisition/config_client.json`: client network and timeout
  settings used by the main robot program.
- `data_acquisition_server/data_acquisition_server.py`: simulated TCP server.
- `data_acquisition_server/config_server.json`: local reference-server
  simulation settings.
