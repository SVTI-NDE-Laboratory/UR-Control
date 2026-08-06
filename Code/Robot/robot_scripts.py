"""URScript builders for robot movements."""

from textwrap import dedent


def ur_list(values: list[float]) -> str:
    """Format a Python list as a URScript list.

    Values are kept compact but precise enough for robot targets.
    """

    return "[" + ", ".join(f"{value:.12g}" for value in values) + "]"


def ur_pose(values: list[float]) -> str:
    """Format six pose values as a URScript pose.

    UR poses are written as p[x, y, z, rx, ry, rz].
    """

    return "p" + ur_list(values)


def movej_script(q: list[float], a: float, v: float) -> str:
    """Build a small URScript program for one joint move.

    The script is intentionally single-purpose so Python can sequence moves.
    """

    script = dedent(
        f"""\
        def python_movej():
          movej({ur_list(q)}, a={a}, v={v})
        end

        python_movej()
        """
    )
    return script


def translate_tool_script(offset: list[float], a: float, v: float) -> str:
    """Build a URScript program that translates in the current tool frame.

    The TCP pose is read on the robot, then transformed by the local offset.
    """

    script = dedent(
        f"""\
        def python_translate_tool():
          start_pose = get_actual_tcp_pose()
          target_pose = pose_trans(start_pose, {ur_pose([offset[0], offset[1], offset[2], 0, 0, 0])})
          movel(target_pose, a={a}, v={v})
        end

        python_translate_tool()
        """
    )
    return script


def movel_pose_script(pose: list[float], a: float, v: float) -> str:
    """Build a URScript program for one linear Cartesian move.

    This is used when the path shape matters more than joint interpolation.
    """

    script = dedent(
        f"""\
        def python_movel_pose():
          movel({ur_pose(pose)}, a={a}, v={v})
        end

        python_movel_pose()
        """
    )
    return script
