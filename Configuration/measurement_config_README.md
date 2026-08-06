# Measurement Configuration

`measurement_config.json` contains the parameters used for the measurement line.

## line

`length`  
Total measurement line length. Unit: `m`.

`increment`  
Distance between two consecutive measurement positions. Unit: `m`.

`direction_start_end`  
Direction of motion from the start of the line to the end of the line. Unit: none. This is a tool-frame vector and is normalized by the program.

## obstacle

`start`  
Start of the obstacle zone measured along the line from the start point. Unit: `m`.

`end`  
End of the obstacle zone measured along the line from the start point. Unit: `m`.

`high_low_distance`  
Distance between the high safe plane and the low measurement plane. Unit: `m`.

`direction_high_low`  
Direction from high position to low position. Unit: none. This is a tool-frame vector and is normalized by the program.

The temporary measurement simulation also uses this direction for its probing displacement.

## measurement

`target_force`  
Force threshold required to start a measurement. Unit: `N`.

`max_displacement`  
Maximum probing displacement allowed while searching for contact. Unit: `m`.

`acceleration`  
Acceleration used for measurement-related `movel` translations. Unit: `m/s^2`.

`speed`  
Speed used for measurement-related `movel` translations. Unit: `m/s`.

`force_reached_limit`  
Force threshold used to decide that contact/force was reached. Unit: `N`. If omitted, the program uses `target_force`.

`force_step_distance`  
Optional step size used by the Python-stepped fallback force approach. Unit: `m`. If omitted, the fallback uses the smaller of `0.001 m` and `max_displacement`.

`force_direction`  
Optional probing direction in the tool frame for the Python-stepped fallback. Unit: none. If omitted, the fallback uses `obstacle.direction_high_low`.

## force_approach_urp

`program_name`  
URP path as seen by the robot Dashboard server. Unit: none. Example: `Benoit/ForceApproach.urp`.

`result_host`  
PC network interface used by Python to listen for the URP result socket message. Unit: none. Use `0.0.0.0` to listen on all local interfaces.

`result_port`  
TCP port used by the URP to send the force approach result to Python. Unit: none.

`timeout`  
Maximum time Python waits for the URP result message. Unit: `s`.

## measurement program file

The URP that may eventually perform the force/displacement measurement is stored at:

```text
Configuration/Measurement Programs/TTS_BAM_-675_700.urp
```

It was copied into the project by:

```powershell
python Code\Measurement\measurement_program_file.py
```

The helper function is:

```python
copy_measurement_program(source_path, destination_path)
```

The URP socket example script is stored at:

```text
Configuration/Measurement Programs/force_result_socket_example.script
```

Add the function in that file to your force approach URP and call it before the
URP ends. The active Python implementation is `Code/Measurement/force_approach_urp.py`.

## data_acquisition

`host`  
IP address or hostname of the data acquisition server. Unit: none.

`port`  
TCP port used by the data acquisition server. Unit: none.

`timeout`  
Maximum time to wait for the data acquisition server response. Unit: `s`.
