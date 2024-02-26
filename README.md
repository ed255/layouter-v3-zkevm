# Halo2 Layouter v3 with advice column merging

This is a script to test a simple layouting algorithm that merges advice
columns tested on the zkevm-circuits.  The zkevm-circuits has 1 region per
subcircuit, and the number of rows per subcircuit is determined by a worst-case
gas/row analysis.  This way we get a supercircuit that can prove the target gas
in the worst case.

# Python dependencies
- `pygame` for drawing the layout result

# Usage
```
./zkevm-worst-case.py
```
