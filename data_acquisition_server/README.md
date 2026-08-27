# Legacy Reference Data Acquisition Server

This folder contains the older simulated data acquisition server. The current
main robot program is now the TCP server and listens according to:

The communication contract for the real server is documented in:

```text
src/program/data_acquisition/protocol.md
```

The main robot program reads its listener settings from:

```text
src/program/data_acquisition/config_server.json
```

This legacy reference server reads only its own simulation defaults from:

```text
data_acquisition_server/config_server.json
```

Run it manually only when testing the previous client/server design:

```powershell
python data_acquisition_server\data_acquisition_server.py
```

Run the interactive fake cobot client in a second terminal:

```powershell
python data_acquisition_server\example_cobot_client.py
```

The example client prints each JSON request/response, keeps a heartbeat active,
and prompts before sending each fake `acquire_data` request. It does not speak
the current `ISREADY`/`GO`/`ALIVE` protocol.
