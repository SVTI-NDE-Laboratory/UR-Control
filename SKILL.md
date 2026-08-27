---
name: pragmatic-coding
description: Apply pragmatic coding standards to all programming-related requests, including writing code, debugging, refactoring, reviewing code, designing small applications, scripting, notebooks, APIs, web applications, data processing, and architecture advice. Default to Python, simple maintainable implementations, established libraries, compact Python formatting, clear separation of responsibilities by module, extensive documentation, complete runnable code, and explanations suitable for an engineer rather than a computer scientist. Prefer FastAPI for Python web APIs and web backends when a framework is actually warranted.
---

# Pragmatic Coding

Apply these standards consistently to programming work.

## Assume an internal engineering-team audience

- Assume the code is for the user and their immediate team, not for sale, public distribution, or unknown external users.
- Assume teammates have similar or less programming experience than the user, so optimize for code that is easy to understand, modify, debug, and hand over internally.
- Do not pursue production-grade perfection by default. Avoid enterprise-grade architecture, exhaustive configurability, premature extensibility, and defensive complexity unless the actual task warrants them.
- Prefer a solid, practical solution that works reliably for the stated use case over a theoretically complete or universally reusable system.
- Still handle obvious errors, unsafe behavior, data-loss risks, and important edge cases. Simplicity is not an excuse for fragile or misleading code.
- If a shortcut is reasonable for internal use, take it and briefly note the limitation only when it matters.

## Optimize for practical simplicity

- Prefer the simplest implementation that solves the actual problem cleanly.
- Avoid abstraction for hypothetical future needs.
- Do not introduce classes, factories, interfaces, dependency-injection layers, inheritance hierarchies, plugin systems, or elaborate architecture unless they solve a concrete current problem.
- Prefer readability and maintainability over computational efficiency by default.
- Optimize performance when the operation is lengthy, repeated at meaningful scale, demonstrably slow, or the user explicitly asks for optimization.
- When several approaches are reasonable, prefer the one an engineer can understand and modify quickly months later.

## Organize code by responsibility

- Separate substantial responsibilities into clearly named modules/files.
- Keep related operations together. For example, put JSON reading, writing, serialization, and closely related JSON helpers in a JSON-focused module instead of scattering them throughout unrelated files.
- Do not split tiny programs into many files merely to satisfy a structural rule. Keep the file structure proportional to the size of the program.
- Keep public entry points and orchestration easy to find.

## Prefer established libraries

- Use popular, actively maintained, widely understood libraries when they already solve the problem well.
- Do not create custom implementations of standard functionality without a concrete reason.
- Prefer standard-library functionality when it is already sufficient and simpler than adding a dependency.
- Briefly explain a non-obvious dependency choice when it materially affects the solution.

## Language and web defaults

- Prefer Python unless another language is clearly better suited to the task or the user specifies one.
- Use JavaScript or TypeScript when browser-side behavior or the surrounding web ecosystem requires it.
- For Python web APIs and web backends, prefer FastAPI when a web framework is warranted.
- Do not introduce FastAPI for tasks that are better handled as a simple script, command-line program, notebook, static page, or lightweight library.
- If another web framework is materially simpler or better matched to an existing project, use it and state the reason briefly.

## Keep Python compact but conventional

- Favor compact formatting without sacrificing clarity or standard Python conventions.
- Keep function signatures on one line when they remain reasonably readable and convention-compliant.
- When a signature must wrap, group logically related parameters sensibly instead of placing every parameter on a separate line.
- Avoid unnecessary vertical expansion of simple expressions, calls, collections, and definitions.
- Never compress code merely to reduce line count when doing so makes the logic harder to understand.
- Follow normal Python naming, indentation, import, typing, and formatting conventions.

## Provide complete runnable code

- When producing code, default to complete runnable code rather than isolated fragments.
- For multi-file solutions, provide every file required to run the example and clearly identify each filename.
- Include imports, entry points, configuration placeholders, and minimal setup needed for execution.
- Do not omit important implementation details behind comments such as `# implement this here` unless the user explicitly asks for pseudocode.
- Keep examples minimal: include what is necessary to demonstrate and run the solution, not unrelated infrastructure.

## Document intent thoroughly

- Add useful docstrings to functions and classes.
- Document what each function intends to do, its important inputs and outputs, assumptions, side effects, and non-obvious behavior.
- Add module-level documentation or a clear introductory comment when the module's overall role is not immediately obvious.
- Explain the purpose and structure of larger programs, including how the main files fit together.
- Document decisions and intent rather than narrating obvious syntax line by line.
- Keep documentation synchronized with the code shown.

## Explain for an engineer

- Assume strong technical and quantitative reasoning but not formal computer-science training.
- Explain unfamiliar programming concepts plainly and concretely.
- Define jargon when it is needed to understand the solution.
- Prefer engineering analogies, data flow, inputs/outputs, constraints, and practical consequences over theoretical terminology.
- Do not over-explain elementary Python syntax unless it is relevant to the issue.

## Respond to coding requests

1. Identify the simplest practical solution that satisfies the request.
2. Choose established libraries only where they reduce code or complexity.
3. Organize responsibilities into a proportionate file structure.
4. Produce complete runnable code by default.
5. Document the code and overall intent.
6. Explain the key design choices in plain engineering terms, especially any non-obvious tradeoffs.
7. Mention performance or architectural alternatives only when they are materially relevant; do not complicate the main solution preemptively.
