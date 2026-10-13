# Newton: coupled Franka + cable pick-and-place

A headless, multi-world version of the Newton Fundamentals [coupled
manipulation](https://docs.nvidia.com/learning/physical-ai/getting-started-with-newton/latest/newton-fundamentals/coupled-manipulation.html)
lesson. A MuJoCo-solved Franka Emika Panda arm picks up a VBD-solved cable and
places it elsewhere; the two solvers are joined by proxy coupling.

- Simulation runs **headless** and records every frame to a `.viser` file.
- Playback is done afterwards in the browser with [viser](https://viser.studio) (no live rendering).
- CLI is built with [tyro](https://brentyi.github.io/tyro/).
- Warp kernels set per-world IK targets and gripper commands, and compute the
  cable centroid / placement error on the GPU.

| File             | Purpose                                                    |
| ---              | ---                                                        |
| `sim.py`         | Scene construction, solvers, IK, Warp kernels, `SimConfig` |
| `main.py`        | tyro CLI (`simulate`, `play` and `clean` subcommands)      |
| `qa.md`          | Status table of every CLI option and how it was verified   |

## Setup

Requires [uv](https://docs.astral.sh/uv/) and, for GPU runs, an NVIDIA GPU with
a recent driver.

```bash
uv sync
```

The first run downloads the Franka asset and compiles Warp kernels. Later runs
use the kernel cache, and should run faster.

## Running

All commands are run from the project root.

### 1. Simulate, then play back later

```bash
uv run main.py simulate                   # writes recordings/franka_cable.viser
uv run main.py play                       # serves that recording
uv run main.py play path/to/other.viser   # serves a specific recording (positional)
uv run main.py play --port 8000           # fixed port instead of a free one
```

`play` prints a URL such as `http://127.0.0.1:39095/?playbackPath=recording.viser`;
open it in a browser and press Ctrl+C in the terminal to stop.

### 2. Simulate and play in one go

```bash
uv run main.py simulate --play [--port 8000]
```

### 3. Choose worlds, length and device

```bash
uv run main.py simulate --sim.num-worlds 16            # more parallel worlds
uv run main.py simulate --sim.steps 120                # only the first 120 frames
uv run main.py simulate --sim.device cpu               # CPU (slow, small world counts)
uv run main.py simulate --sim.device cuda:1            # pick another GPU
uv run main.py simulate --sim.speed 2.0                # 2x faster task timing
```

### 4. Change the cable and task

```bash
uv run main.py simulate --sim.cable-segments 31 --sim.cable-length 0.45
uv run main.py simulate --sim.cable-bend-stiffness 5e-3 --sim.cable-density 200
uv run main.py simulate --sim.place-x 0.3 --sim.place-y -0.2
```

### 5. Tune solvers and output

```bash
uv run main.py simulate --sim.substeps 20 --sim.mujoco-iterations 150 --sim.vbd-iterations 30
uv run main.py simulate --sim.output out/run1.viser --sim.world-spacing 2.0
uv run main.py simulate --sim.no-verbose               # no progress bar or summary
uv run main.py simulate --quiet                        # silence Warp's init/compile messages
uv run main.py simulate --sim.profile                  # per-kernel GPU timing table
uv run main.py simulate --sim.fps 30 --sim.ik-iterations 10 --sim.coupling-iterations 2
```

### 6. Remote / headless machines

Simulation needs no display. To view the playback from your laptop, run `play`
on the remote machine and forward the printed port:

```bash
ssh -L 39095:127.0.0.1:39095 user@remote
# then open http://127.0.0.1:39095/?playbackPath=recording.viser locally
```

Or copy the `.viser` file to a machine that has the project and run `play` there.

### 7. Domain randomization

Each world can get its own random parameters, sampled from `--sim.seed`:

```bash
uv run main.py simulate --sim.rand.all                       # every parameter, default ranges
uv run main.py simulate --sim.rand.friction 0.5              # only cable friction, +-50%
uv run main.py simulate --sim.rand.all --sim.rand.timing 0   # everything except task timing
```

| Flag (`--sim.rand.<name>`) | Randomizes                                       | Unit     | Default range |
| ---                        | ---                                              | ---      | ---           |
| `friction`                 | cable friction coefficient                       | relative | 0.3           |
| `contact-ke`               | cable contact stiffness and damping              | relative | 0.2           |
| `cable-mass`               | cable mass and inertia                           | relative | 0.3           |
| `arm-gains`                | Franka arm PD gains                              | relative | 0.2           |
| `cable-pos`                | cable start position (x, y); the grasp follows   | metres   | 0.03          |
| `place-pos`                | place target (x, y)                              | metres   | 0.05          |
| `timing`                   | task speed (the run is lengthened for slow worlds) | relative | 0.1         |

A value is a uniform half-range around nominal. Unset means off, or the default
if `--sim.rand.all` is given; `0` always disables a parameter. Draw order is
fixed, so enabling one parameter does not change the samples of the others.

Not randomized yet:

- Cable geometry (segment count, length, radius). These define the model
  topology, which is shared by all worlds.
- Cable bend and stretch stiffness (and damping). They are baked into the rod
  joints by `add_rod`, so a per-world version needs the matching joint arrays edited.
- Cable yaw, and the ground plane's own material. The ground is a single shape
  shared by all worlds.
- Franka initial pose, gripper force and finger gains, and sensor/actuation noise.

### 8. Clean caches

```bash
uv run main.py clean                 # Warp kernel + LTO caches, and Newton's downloaded assets
uv run main.py clean --keep-assets   # keep the Franka asset (no re-download)
```

The next `simulate` recompiles kernels (about 30-50 s) and, after a full clean, re-downloads the Franka asset.

### Input checking

Impossible values are rejected up front with a one-line `error: ...` (non-positive
world count / fps / substeps / speed, fewer than 2 cable segments, negative `--sim.steps`,
a missing GPU, relative randomization ranges >= 1, a missing recording for `play`).

### Help

```bash
uv run main.py --help
uv run main.py simulate --help     # lists every option with defaults
```

## Notes

- Each world has its own Franka and cable. Worlds are simulated at the origin
  and only offset visually (`--sim.world-spacing`) for playback.
- `--sim.steps` counts frames; by default the full 7 s task (420 frames at 60 fps) is run.
  Values beyond the task length hold the final pose.
- The recorder starts a viser server (default port 8080) while simulating, so a banner
  appears even with `--quiet`. If the port is taken, viser moves to the next free one (tested).
- Runs are not bit-for-bit reproducible, even with the same `--sim.seed`: the random
  parameters are identical, but GPU contact/solver ordering makes the final placement error vary by
  a centimetre or more between runs (and between different world counts).
- The final printed per-world "placement error" is the horizontal distance from
  the cable centroid to the place target; expect roughly 1-6 cm with defaults (it varies run to run; see above).
- `play` relies on a private Newton method (`ViewerViser._serve_viser_recording`)
  and may need updating on Newton upgrades.
