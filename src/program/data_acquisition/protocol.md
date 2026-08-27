# Data Acquisition Control Protocol

The main robot program is the TCP server. It listens on the host/port from:

```text
src/program/data_acquisition/config_server.json
```

The external acquisition client connects and sends one command per TCP
connection, followed by `\n`. Requests may be plain text such as `ALIVE` or JSON
such as `{"message": "ALIVE"}`. Responses are plain text followed by `\n`.

At startup, the robot program starts listening and waits until the client sends
`ALIVE`. Only then does the measurement sequence continue.

## Commands

`ALIVE`

Returns:

```text
OK
```

This marks the external client as ready.

`ISREADY`

Returns:

```text
T
```

only while `apply_force` has reached the force threshold and the robot is
holding force during a measurement. Otherwise it returns:

```text
F
```

`GO`

Returns:

```text
ACK
```

If force is currently reached and waiting, `GO` releases the hold so the robot
program can acknowledge register 42 and continue. If no measurement is ready,
`ACK` is still returned but no motion state changes.

## Timeouts

- `client_ready_timeout`: maximum startup wait for the first `ALIVE`.
- `go_timeout`: maximum wait for `GO` after `ISREADY` becomes `T`.
