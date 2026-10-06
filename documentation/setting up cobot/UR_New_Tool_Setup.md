# Setting Up a New Tool on a Universal Robot

When attaching a new tool to the robot flange, configure the installation so the robot knows:

- where the tool contact point is,
- how much the tool weighs,
- where its center of gravity is,
- and how the tool I/O is configured.

For force-controlled applications, the TCP and payload configuration should be as accurate as possible.

## 1. Define the TCP

Go to:

**Installation → General → TCP**

Create a new TCP, for example:

`MIRA_TCP`

The TCP defines the position and orientation of the useful tool point relative to the robot flange.

For an inspection tool, this is normally the actual contact or measurement point.

If the TCP coordinates are not known precisely, use **Measure**. PolyScope can calculate the TCP position by touching the same fixed point from several different tool orientations.

Set the new TCP as the default TCP if it is the tool normally used with the installation.

### Important

The TCP is not the same thing as the center of gravity.

For example, if the tool center of gravity is 150 mm from the flange, this does **not** mean the TCP should be set to 150 mm.

The TCP should represent the actual measurement or contact point.

---

## 2. Define the Payload

Go to:

**Installation → General → Payload**

Create a new payload, for example:

`MIRA_payload`

The payload should include everything mounted on the robot flange that moves with the robot, including:

- inspection device,
- adapter plates,
- brackets,
- sensors,
- connectors,
- and relevant moving cables.

The important parameters are:

- **Mass**
- **Center of Gravity (CoG)**
- **Inertia**, when available

The CoG is defined relative to the tool flange.

If the exact payload and CoG are not known, use the **Payload Estimation / Measure** function in PolyScope.

The robot will ask you to move the tool into several sufficiently different poses. From these measurements it can estimate the mass and center of gravity.

This is generally preferable to entering rough estimates.

---

## 3. Set the Payload as Default

After defining the payload, select it and set it as the default payload for the installation.

The correct payload model should be active whenever the robot operates with that tool.

If the tool or payload changes during a program, the active payload must also be updated accordingly.

---

## 4. Check the Robot Mounting

Go to:

**Installation → General → Mounting**

Verify that the robot mounting orientation matches the physical installation.

This is important because the robot uses the mounting orientation to determine the direction of gravity.

An incorrect mounting configuration can affect:

- payload estimation,
- gravity compensation,
- force measurements,
- and force control.

---

## 5. Configure Tool I/O if Required

If the tool uses the electrical interface on the robot flange, go to:

**Installation → General → Tool I/O**

Configure the required:

- tool voltage,
- digital inputs,
- digital outputs,
- and other tool I/O settings.

This configuration is separate from the TCP and payload settings.

---

## TCP vs Payload

These two concepts should be kept separate.

### TCP

Defines:

> Where is the useful point of the tool?

For example, the contact point between the MIRA device and the inspected surface.

### Payload

Defines:

> What mass is attached to the robot, and where is that mass located?

For example, a 4 kg device with its center of gravity approximately 150 mm from the flange.

---

## Importance for Force-Controlled Operations

For force-controlled applications, accurate TCP and payload settings are especially important.

Incorrect payload or CoG values can cause the robot's force/torque estimate to contain gravity-related errors.

These errors may change depending on robot orientation.

Before performing force-controlled measurements, verify:

1. TCP
2. Payload mass
3. Payload center of gravity
4. Robot mounting orientation
5. Tool I/O, if applicable

If possible, use the PolyScope measurement procedures instead of relying only on estimated values.
