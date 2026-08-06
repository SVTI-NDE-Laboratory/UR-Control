# Data Acquisition Server

This folder contains a simulated acquisition server.

`Code\Program\main.py` starts this server automatically.

Start it manually only when testing the server by itself:

```powershell
python "Data Acquisition Server\data_acquisition_server.py"
```

Protocol:

```json
{
  "message": "acquire_data",
  "request_id": "measurement_0",
  "line_index": 0,
  "line_position": 0.0,
  "tcp_pose": [0, 0, 0, 0, 0, 0],
  "tcp_force": [0, 0, 0, 0, 0, 0]
}
```

Response:

```json
{
  "message": "data_acquired",
  "acquisition_time": 1.42,
  "request_id": "measurement_0"
}
```

For now, acquisition is simulated with a random wait between 1 and 2 seconds.
