Description UR program.

Description of waypoints:
- Home: home position of the robot
- p_start_h: "p" means position, "start" that it is at the start of the measurement and "h" means high. This point is at the start of the measurement sequence in a high position (considered safe).
- p_start_l: same as above, but at a low position. Theoritically, "h" and "l" must not be vertical. It just defines two planes parallel to the measurement plane. One close to it ("l"), one further ("h").
- Tmp1, Tmp2: temporary points just to allow the transition from "Home" to "p_start_h"

Boradly speaking, the program is composed from three steps:
- Start routine: move robot from "Home" to first element to measure (p_start_h) 
- Measurements: the robot moves from point to point, performing a measurement at each point.
- End routine: robot returns to start of measurements (p_start_h) and the to "Home".

The start and end routines are defined in a routines.json file (or similarly named).
The file indicates all relevant waypoints, their order of execution and speed, acceleration, etc.
The start routine is called "start" and end routine "end".
A program reads the routines, and start the cobot to perform one or the other. Theoritically, other routines could be applied

The measurements part is where measurements are recorded with a device place on the robot tool flange.
The cobot moves to various position and performs a measurement procedure.
The procedure is:
- Move perpendicular to the tool flange (from "l" position)
- During movement, measure force until it reaches a given value:
	- Succesfully reached force: stop at this position (Success: measurement can start)
	- Did not reach force but reached maximum distance (Fail: no measurement possible)
- If success, Cobot waits for a signal that measurement is done
- Move back to "l" position
The procedure is defined in a urp file. The program is launched at each measurement. 
UR-RTDE is used to indicate to the control program if a success or fail happened. 
Then, once the measure has been saved, the control program can set the register to finish the measurement procedure.

The program then handles the position of the robot along a line so it can start the measurement procedure.
Essentially, it translates along a line with fixed distance increments until it reaches the maximum distance of the line.
Important is that there is also an obstacle located along the line where the cobot needs "move" above it and go to the next available position.

How it works:
- At the beginning of each iteration (given index, given position):
	- Do I need to measure here?
		- Yes: go to low mode (maybe already) and perform measurement
		- No: do nothing
	- Analysis of next point: measurement, obstacle or finished.
		- Measurement: Move to low mode (if not already), translate
		- Obstacle: Move to high mode (if not already), translate
		- End: do nothing

The movements are all performed using the same communication protocol as for the start and end routine, but with translation from the current position.
Note that the cobot start the line in high mode. So it should account for that also.

The following information must be set before starting the program (in a json):
Relative to where to do the measurements:
	- Total distance of line
	- Line increment
	- Distance between high (safe) and low positions
	- Position of obstacle along the line (where can we not perform a measure)
	
Relative to measurement:
	- Target force
	- Maximal displacement
	- Safe speed and accelerations

The following information must always be present during the program:
- What is the program doing: Idle, start_routine, measurements, end_routine
- Where is the robot along the line: "index", linear position, low or high mode, obstacle or not, etc.
- Maybe some other things that I am not thinking of.

What I'd like you to do is to prepare an entire program that does all that. 
Right now, no UI, just loading a JSON of the routine and JSON of the "before start" information.
Rules: keep the code as simple as possible, no need to check all inputs for now, also, keep inputs on same line as much as possible. 
Before going further, suggest a clear structure of my folder, of files etc that I need to approve.
Ask question if something is not clear.
Make suggestion if I miss something.