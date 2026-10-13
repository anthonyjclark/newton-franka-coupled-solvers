# QA status

Run on 2026-10-12, RTX PRO 6000 Blackwell (1 GPU), via `uv run main.py ...`.
"Short" = `--sim.steps 60` (1 s); "full" = the whole 7 s task. Placement error is the
final cable-centroid distance to the place target; short runs have not placed the cable yet, so ~0.27 m is expected there.

Legend: PASS = works as documented, FIXED = problem found and fixed, NOTE = works, behaviour to be aware of.

## Subcommands

| Option | Test | Status | Notes |
| --- | --- | --- | --- |
| `--help` (top level, `simulate`) | printed | PASS | |
| `simulate` (defaults) | full, 4 worlds | PASS | 43 s, errors 0.02-0.05 m |
| `simulate --play` | short, served, HTTP 200 | PASS | |
| `simulate --port N` (with `--play`) | port 39556, HTTP 200 | PASS | |
| `simulate --quiet` | full | NOTE | Silences Warp only; the viser banner still prints |
| `play` (default path) | served, HTTP 200 | PASS | |
| `play <path>` | | FIXED | README example failed with "Unrecognized options"; `recording` is now positional |
| `play --port N` | 39555, `recording.viser` HTTP 200 | PASS | |
| `play` output | | FIXED | URL was block-buffered when piped; now flushed |
| `play <missing file>` | | FIXED | Was an obscure failure; now `error: recording not found` |
| `clean --keep-assets` | then simulate | PASS | Kernels recompiled |
| `clean` | then simulate | PASS | Franka asset re-downloaded (needs network) |

## `--sim.*` options

| Option | Test | Status | Notes |
| --- | --- | --- | --- |
| `num-worlds` | 1, 4, 16 | PASS | 16 worlds ~146 world-frames/s |
| `num-worlds 0` | | FIXED | Was a reshape traceback; now validated |
| `steps` | 0, 20, 60, 500 | PASS | Beyond task length holds final pose |
| `steps -3` | | FIXED | Now validated |
| `device` cpu | 10 frames, 1 world | PASS | 0.6 world-frames/s |
| `device` cuda:0 | all runs | PASS | |
| `device` cuda:1 / cuda:7 (absent) | | FIXED | Was a traceback; now `error: ... not available` |
| `fps` 30 | short | PASS | |
| `fps 0`, `substeps 0` | | FIXED | Were ZeroDivisionError; now validated |
| `substeps` 20 | short | PASS | |
| `ik-iterations` 10 | short | PASS | |
| `cable-segments` 31 | short | PASS | |
| `cable-segments 1` | | FIXED | Was a Newton traceback; now `must be >= 2` |
| `cable-length`, `cable-radius` | short | PASS | |
| `cable-density`, `cable-bend-stiffness`, `cable-stretch-stiffness` | short | PASS | Short run only; no check of grasp quality |
| `cable-height`, `cable-x`, `approach-height` | short | PASS | Short run only |
| `place-x`, `place-y` | full (0.3, -0.2) | PASS | error ~0.018 m |
| `speed` 2.0 | full | PASS | 210 frames, error ~0.011 m |
| `speed 0` | | FIXED | Silently produced infinite keyframe times; now validated |
| `mujoco-iterations` 150 | short | PASS | |
| `vbd-iterations` 30 | short | PASS | |
| `coupling-iterations` 2 | short | PASS | |
| `world-spacing` 2.0 | short | PASS | Visual only; recording not inspected in a browser |
| `output` (nested new dir) | `sub/dir/out.viser` | PASS | Parent dirs created |
| `seed` | 0, 5, 7 | PASS | Different seeds give different random parameters |
| `verbose` / `no-verbose` | short | PASS | `no-verbose` prints only the final "Recording written" line |
| `profile` | short | PASS | Kernel table printed |

## Domain randomization (`--sim.rand.*`)

| Option | Test | Status | Notes |
| --- | --- | --- | --- |
| `all` | full, 4 and 6 worlds | PASS | Errors differ per world; timing lengthens run (431-465 frames) |
| `friction`, `contact-ke`, `cable-mass`, `arm-gains` | short, 3 worlds | PASS | Start up and run; effect on outcome not isolated |
| `cable-pos`, `place-pos` | short, with seed 7 | PASS | |
| `all` + `timing 0` | short | PASS | `timing` omitted from printed ranges |
| relative value >= 1 or negative | | FIXED | Used to be accepted (negative/zero scale factors); now validated |

## Other

| Item | Status | Notes |
| --- | --- | --- |
| Port 8080 already in use while simulating | PASS | viser picks 8081. README previously said untested |
| Reproducibility with same seed | NOTE | Parameters identical; results and files not bit-identical (GPU ordering). Placement error varies ~1 cm between runs, and 1-world vs 4-world runs differ (0.052 vs 0.019 m) |
| Playback visual correctness in a browser | NOT TESTED | Only HTTP 200 on the page and recording file; no one looked at it |
| Randomization effect size per parameter | NOT TESTED | |
| `ruff check` | NOTE | 6 pre-existing style warnings remain in `sim.py` (dict() calls, import alias, a broad `except` around `set_camera`) |
| README / `main.py` docstring | FIXED | Stale `coupled_sim.py`, `--num-worlds`, `play <path>`; added `clean`, `--quiet`, `--profile`, validation, reproducibility notes |

## Code changes made

- `main.py`: `Play.recording` positional, missing-file check, flushed playback URL, `error:` exit for `ValueError`/`FileNotFoundError`, docstring flags.
- `sim.py`: `SimConfig.validate()` and `Randomization.validate()`, called from `CoupledFrankaCable.__init__`; removed an unused variable in `_build_ik`.
