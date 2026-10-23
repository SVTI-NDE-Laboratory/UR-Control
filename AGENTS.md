# Coding preferences

Use these preferences when writing or editing code in this workspace. The user's
edits to `visualize_force/scripts/apply_force_from_ur_settling.script` illustrate
the preferred style.

- Organize procedural code in execution order: configuration, initialization,
  main loop, cleanup, and completion. Group internal state initialization near
  the loop that uses it; keep operator-facing variables in the configuration.
- Add concise comments above each logical block and significant conditional
  branch, explaining its purpose or condition in plain engineering language.
- Use blank lines between logical blocks and substantial branches to make the
  control flow easy to scan. Keep tightly related actions together.
- Keep function signatures and calls on one line when readable. For a wrapped
  call, put the first argument on the opening-parenthesis line and the last
  argument on the closing-parenthesis line. Group related arguments together.
- Centralize state messages in an indexed function near the beginning of a
  state-driven script. Select messages by index in the control flow.
- Document register direction, number, meaning, and units near the beginning;
  put status-code explanations beside the register-handshake logic.
- Explain timing, limits, coordinate frames, and state transitions where they
  matter. Keep comments technically accurate and consistent with the code.
- Describe what the code does now. Avoid development history, references to
  previous implementations, and unnecessary emphatic wording or capitalization.
- Preserve the user's manual edits and established style when making changes.
- Preserve measurement configuration order: `line`, `obstacle`,
  `points_selections`, `force`, then `motion`. In `line`, use `steps` and
  `nb_points`. Always retain obstacle `present`, `width`, `position`, and
  calculated `start`/`end`, even when absent. Within `force`, keep:
  `program_path`, `target_force`, `settling_time`, `max_displacement`,
  `stop_method`, `hold_duration`, `simulation`, `simulation_program_path`.
  Do not sort keys when writing configuration files.
