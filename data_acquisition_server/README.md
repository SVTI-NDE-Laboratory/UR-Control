# Simulated Data Acquisition Server

The main robot program starts this local TCP server and verifies it with an
application-level handshake before connecting to the robot. When force is
reached, the main program requests one acquisition and keeps the robot force
hold active until the server replies.

- `data_acquisition_server.py`: simulated server.
- `data_acquisition_client.py`: request client.
- `data_acquisition_server_process.py`: child-process lifecycle and handshake.
- `config.json`: local network, timeout, and simulated-delay settings.

The simulated server waits a random 1-3 seconds and returns `data_acquired` with
a completion timestamp. On Windows, main launches it in a separate visible
console so its handshake and acquisition messages can be monitored directly.
The same timestamped output is flushed in real time to
`data_acquisition_server.log` in the active program output folder.
It can also be tested manually:

```powershell
python data_acquisition_server\data_acquisition_server.py
```

It accepts an `acquire_data` JSON message and replies with `data_acquired`
after a simulated delay.
