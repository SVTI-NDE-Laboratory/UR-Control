# Program entry point

`main.py` runs the complete sequence:

```text
start routine -> measurements -> end routine
```

It reads:

```text
src/routines/routine_files/routines_block.json
src/program/config/config.json
```

It writes:

```text
src/program/config/state.json
```

Data acquisition is not currently part of this sequence. The optional placeholder
implementation is kept separately in `data_acquisition_server`.

The script asks for terminal confirmation before connecting and moving.

```powershell
python src\program\main.py
```
