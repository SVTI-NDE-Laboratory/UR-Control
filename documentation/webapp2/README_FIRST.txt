RTM COBOT STUDIO — FIRST USE

SAFETY FIRST
- Use only with trained/authorized operators and an approved installation risk
  assessment. Confirm the correct tool, payload, fixture and taught paths.
- UR15 operating temperature: 0–50 °C; reduced performance from 35 °C upward.
  Keep relative humidity below the 90% limit, with no condensation. Apply any
  stricter limits for the tool or installation.
- Wear the workstation's required safety shoes and other assessed PPE, including
  eye protection or suitable gloves where required. Secure hair and loose items.
- Know the physical emergency stops. The app's Stop button is not a substitute.
  Simulation still moves the robot and can apply force during approach.
See section 1 of USER_MANUAL.html or USER_MANUAL.docx for conditions and UR sources.

FIRST LAUNCH
1. Extract the release zip into a normal folder on a 64-bit Windows PC.
   Python is included. Do not launch the exe from inside the zip.
2. For a new setup, extract RTM Cobot Studio-default-data.zip. Place its "RTM Cobot Studio"
   folder under %LOCALAPPDATA% or another writable local folder. Never overwrite
   existing working data with the default archive.
3. Start RTM Cobot Studio.exe. If asked, select the extracted folder containing
   preferences.json. Selecting an empty folder instead creates defaults.
4. Check Settings before motion. Supplied IP: 192.168.3.10; supplied routine:
   routine.json. These coordinates are specific to the existing setup.
   The matching Apply Force URP must already be installed on the controller.
   Starter robot programs, routine scripts and routines are copied only into an
   empty local data folder. Startup and upgrades never restore deleted files or
   add starter files to existing data. The user manages these libraries afterward.

USE AND SHUTDOWN
Keep the PC awake and connected; run only one robot-control application.
Stop current action aborts and does not return Home. Follow the approved return
procedure, then use Close app. Closing only the browser tab can leave it running.
If the tab does not open, copy the local URL from the console window.

MANUAL AND UPDATES
The concise HTML/Word manual covers each tab and has space for approved robot
startup, Apply Force updates and WinSCP examples. Complete these before handover;
save your edited Word copy under a separate installation-specific filename.
To update: close the app, replace the exe and keep the local data folder.
