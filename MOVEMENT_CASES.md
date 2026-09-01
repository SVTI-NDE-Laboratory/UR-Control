# Point-To-Point Movement Cases

This document describes the movement logic used during point-to-point force
measurements. It focuses on the route between the taught points:

```text
p_start_h
   |
p_start_l -------------- p_end_l
                           |
                         p_end_h
```

`p_start_l -> p_end_l` is the measurement line. `p_start_h` and `p_end_h` are
safe taught waypoints used only to enter or leave the line through taught robot
routines.

## Core Rules

- The robot must start at `Home`.
- The robot must not translate along the line while it is at `p_start_h`,
  `p_end_h`, or any high pose.
- To reach a measurement position, the robot first goes to the matching low
  taught line endpoint, either `p_start_l` or `p_end_l`, then translates along
  the low line.
- If `offset_y` is configured, every low-level line translation stays on the
  offset measurement line.
- The robot leaves the offset measurement line only at `p_start_l` or
  `p_end_l`, immediately before moving up to `p_start_h` or `p_end_h`.
- Points inside the configured obstacle interval are skipped.
- If the segment between two valid measurement points crosses an obstacle, the
  robot uses the taught Home detour instead of translating through the obstacle.

## Case 1: No Obstacle Before The First Point

This is the normal start-side flow.

```text
Home
-> home_to_start routine
-> p_start_h
-> p_start_l
-> apply Y offset if configured
-> first measurement point
```

After that, the robot measures valid points in order. Between two valid points,
if the path does not cross an obstacle, it translates directly along the low
measurement line.

```text
current low measurement point
-> translate on low measurement line
-> next low measurement point
```

## Case 2: Obstacle Blocks The First Measurement Point

If the first planned point is inside the obstacle, the robot does not go to
`p_start_h`. It starts from the end side.

```text
Home
-> home_to_end routine
-> p_end_h
-> p_end_l
-> apply Y offset if configured
-> translate on low measurement line
-> first available measurement point after the obstacle
```

The important part is that the robot descends to `p_end_l` before any line
translation. It never translates from `p_end_h`.

## Case 3: Obstacle After One Or More Measurements

The robot measures normally from the start side until the last available point
before the obstacle. When the next valid point would require crossing the
obstacle, it returns through the taught start-side route, crosses through Home,
then enters from the end side.

```text
last valid low measurement point before obstacle
-> translate on the offset low measurement line to p_start_l
-> return from Y offset to the taught p_start_l, if needed
-> p_start_h
-> start_to_home routine
-> Home
-> home_to_end routine
-> p_end_h
-> p_end_l
-> apply Y offset if configured
-> translate on low measurement line
-> first available measurement point after the obstacle
```

Again, the robot does not translate along the high plane. The high waypoints
are used only as taught entry/exit points for the Home detour.

## Case 4: Measurement Point Inside The Obstacle

Any sampled measurement point inside the obstacle interval is skipped. The plan
keeps the point with:

```json
{
  "measured": false,
  "skip_reason": "obstacle"
}
```

If skipped points are at the beginning of the line, Case 2 applies. If skipped
points appear after earlier measurements, Case 3 applies.

## Case 5: Force Reaches Maximum Displacement

If force is not reached before `max_displacement`, the force program first
returns to the initial low measurement pose where force application started.
Then Python recovers to the safe high waypoint on the same side of the
obstacle.

If the failed position is on the start side:

```text
failed low measurement point
-> move on the offset low measurement line to p_start_l
-> return from Y offset to the taught p_start_l, if needed
-> p_start_h
-> stop sequence
```

If the failed position is on the end side:

```text
failed low measurement point
-> move on the offset low measurement line to p_end_l
-> return from Y offset to the taught p_end_l, if needed
-> p_end_h
-> stop sequence
```

When no obstacle is configured, the recovery side is the nearest line endpoint.

## End Of Measurement Line

After the last successful measurement, the robot finishes at a safe high pose.

If the robot is still on the low measurement line:

```text
last low measurement point
-> move on the same low measurement line to the end-of-line position if reachable without crossing obstacle
-> return from Y offset to taught low line, if needed
-> move low -> high
```

The main measurement command then runs the configured end routine back to Home.

## Relevant Files

- `src/program/commands/run_measurement_sequence.py`: chooses whether startup
  begins through `home_to_start` or `home_to_end`.
- `src/measurement/run_measurements.py`: measures points, skips obstacle
  points, routes around obstacles, and handles force-failure recovery.
- `src/measurement/measurement_movement.py`: low/high and line-translation
  movement helpers.
- `src/measurement/line_planner.py`: point-to-point geometry, obstacle checks,
  and generated measurement positions.
