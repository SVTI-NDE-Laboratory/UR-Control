"""Extract selected waypoints from a Universal Robots `.script` file.

PolyScope-generated script files commonly store taught waypoints as globals:

    global Tmp1_p=p[x, y, z, rx, ry, rz]
    global Tmp1_q=[q1, q2, q3, q4, q5, q6]

where:

- `*_p` is the TCP pose in base coordinates: meters + axis-angle radians.
- `*_q` is the joint configuration in radians.

Some waypoint labels, such as `Home` in `paths_Stefan.script`, are not stored as
`Home_p`. They appear only in the program body as a labeled `movej([...])`.
For those cases this module returns `{"q": [...]}` only. Without robot forward
kinematics, a joint-only waypoint cannot be plotted as an XYZ position.
"""

import re
from pathlib import Path
from typing import TypeAlias


WaypointData: TypeAlias = dict[str, list[float]]
WaypointDict: TypeAlias = dict[str, WaypointData]

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
POSE_RE = re.compile(rf"global\s+([A-Za-z_][A-Za-z0-9_]*)_p\s*=\s*p\[({NUMBER}(?:\s*,\s*{NUMBER}){{5}})\]")
JOINT_RE = re.compile(rf"global\s+([A-Za-z_][A-Za-z0-9_]*)_q\s*=\s*\[({NUMBER}(?:\s*,\s*{NUMBER}){{5}})\]")
LABEL_RE = re.compile(r'\$\s+\d+\s+"([^"]+)"')
MOVEJ_Q_RE = re.compile(rf"movej\(\s*\[({NUMBER}(?:\s*,\s*{NUMBER}){{5}})\]")
MOVE_WITH_POSE_VAR_RE = re.compile(r"(?:get_inverse_kin\(|movel\()\s*([A-Za-z_][A-Za-z0-9_]*)_p\b")


def parse_numbers(text: str) -> list[float]:
    """Return all numbers in `text` as floats.

    Handles normal decimals and scientific notation from URScript output.
    """

    return [float(value) for value in re.findall(NUMBER, text)]


def extract_waypoints_from_script(script_path: str | Path, names: list[str]) -> WaypointDict:
    """Return pose/joint data for the requested waypoint names.

    Args:
        script_path: Path to a PolyScope-generated `.script` file.
        names: Waypoint names to return, for example `["Home", "Tmp1"]`.

    Returns:
        A dictionary keyed by requested name. Each value can contain:

        - `"p"`: Cartesian TCP pose `[x, y, z, rx, ry, rz]`.
        - `"q"`: Joint vector `[base, shoulder, elbow, wrist1, wrist2, wrist3]`.

        Missing waypoints are returned as an empty dictionary, e.g.
        `{"Unknown": {}}`. The function does not raise for missing names because
        that makes batch extraction easier to inspect.

    Example:
        ```python
        points = extract_waypoints_from_script(
            "src/routines/polyscope_scripts/paths_Stefan.script",
            ["Home", "Tmp1", "Tmp2", "p_start_h"],
        )

        print(points["Tmp1"]["p"])  # Cartesian pose
        print(points["Home"]["q"])  # Home is joint-only in this file
        ```
    """

    text = Path(script_path).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    poses = {match.group(1): parse_numbers(match.group(2)) for match in POSE_RE.finditer(text)}
    joints = {match.group(1): parse_numbers(match.group(2)) for match in JOINT_RE.finditer(text)}

    result = {}
    for name in names:
        item = {}

        if name in poses:
            item["p"] = poses[name]
        if name in joints:
            item["q"] = joints[name]

        if not item:
            item = read_waypoint_from_program_lines(name, lines, poses, joints)

        result[name] = item

    return result


def read_waypoint_from_program_lines(
    name: str,
    lines: list[str],
    poses: dict[str, list[float]],
    joints: dict[str, list[float]],
) -> WaypointData:
    """Resolve waypoints that exist as labels in the program body.

    This handles patterns like:

        $ 10 "Home"
        movej([q1, q2, q3, q4, q5, q6], ...)

    and:

        $ 12 "Tmp1"
        movej(get_inverse_kin(Tmp1_p, qnear=Tmp1_q), ...)
    """

    for index, line in enumerate(lines):
        label = LABEL_RE.search(line)
        if not label or label.group(1) != name:
            continue

        for command in lines[index + 1 : index + 6]:
            direct_joint_move = MOVEJ_Q_RE.search(command)
            if direct_joint_move:
                return {"q": parse_numbers(direct_joint_move.group(1))}

            pose_move = MOVE_WITH_POSE_VAR_RE.search(command)
            if pose_move:
                pose_name = pose_move.group(1)
                item = {}
                if pose_name in poses:
                    item["p"] = poses[pose_name]
                if pose_name in joints:
                    item["q"] = joints[pose_name]
                return item

    return {}


if __name__ == "__main__":
    waypoints = extract_waypoints_from_script(
        "src/routines/polyscope_scripts/paths_Stefan.script",
        ["Home", "Tmp1", "Tmp2", "p_start_h"],
    )
    print(waypoints)
