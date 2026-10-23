"""Infer reversible waypoint neighbors from explicitly taught routine steps."""


def waypoint_motion_options(name, waypoint):
    """Apply manual motion restrictions in addition to available taught targets."""
    joint_only = name.lower() == "home" or name.lower().startswith("home_to") or "_to_home" in name.lower()
    linear_only = name in {"p_start_l", "p_end_l"}
    return {"linear": "p" in waypoint and not joint_only,
            "joint": "q" in waypoint and not linear_only}


def waypoint_motion_limits(data):
    """Use routine maxima in mm/s and mm/s² for linear, rad/s and rad/s² for joint."""
    limits = {}
    for motion_type, fallback in (("l", 150.0), ("j", 0.5)):
        motions = [step["motion"] for routine in data["routines"] for step in routine["steps"]
                   if step.get("motion", {}).get("type", "").lower() == motion_type]

        # Retain manual limits when the file teaches no motion of this type.
        limits[motion_type] = {field: max((motion[field] for motion in motions), default=fallback)
                               for field in ("speed", "acceleration")}
    return limits


def routine_transitions(data):
    transitions = []
    for routine in data["routines"]:
        steps = routine["steps"]
        for previous, following in zip(steps, steps[1:]):
            motion = following.get("motion", {}).get("type")
            if motion in {"j", "l"}:
                for source, target in ((previous["waypoint"], following["waypoint"]),
                                       (following["waypoint"], previous["waypoint"])):
                    transitions.append({"source": source, "target": target,
                                        "motion": motion, "routine": routine["name"]})
    waypoints = data.get("waypoints", {})
    for high, low in (("p_start_h", "p_start_l"), ("p_end_h", "p_end_l")):
        if high in waypoints and low in waypoints:
            for source, target in ((high, low), (low, high)):
                transitions.append({"source": source, "target": target,
                                    "motion": "l", "routine": None})
    return transitions


def waypoint_warning(data, source, target, motion):
    """A known target alone does not establish an allowed path to that target."""
    if source and (source == target or any(
        step["source"] == source and step["target"] == target and step["motion"] == motion
        for step in routine_transitions(data)
    )):
        return None
    movement = "linear" if motion == "l" else "joint"
    if source:
        reason = f"The routines do not define a direct {movement} move from {source} to {target}."
    else:
        reason = f"The current robot position does not match a taught waypoint. The {movement} path to {target} cannot be checked against the routines."
    return f"It seems this move may not be safe.\n\n{reason}\n\nAre you sure you want to move forward?"
