# Mandatory container unit coverage

The owner requires unit coverage to be checked on **every container change**.

- Run `python3 tools/container_checks.py` from the repository root before any
  container build, publication or claim that a change is verified.
- Measure both default Rust and `--features web`, including `src/main.rs`, all
  library modules and the browser JavaScript. Runtime files must not be excluded.
- Require 100% executable line coverage and 100% function coverage. Report branch
  coverage separately. Only test source files may be excluded from measurement.
- Cover errors, bounds, stale/lease fencing, reconnects, heartbeat and the absence
  of periodic flash writes with assertions; execution alone is insufficient.
- Keep reports outside tracked source. Bind a passing result to the exact current
  container source digest so stale reports cannot authorize different images.
- Do not lower thresholds, add coverage-ignore attributes, or skip tests to make
  a failing change pass. Preserve minimal release dependencies and scratch images.
- After runtime behavior changes, also exercise the resulting image on the
  isolated CHR. Unit coverage complements actual RouterOS acceptance.
