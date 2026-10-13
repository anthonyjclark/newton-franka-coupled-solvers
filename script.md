# Demo walkthrough script

A guided tour of the coupled Franka + cable demo. Each section gives the
**command**, what to **say**, and what to **point out**. Total time is about
about 15 minutes of talking plus about 5 minutes of simulation time (measured
timings are in each section; worst case with every optional section is about
31 minutes). Run everything from the project root. Timings were measured on one
CUDA GPU with a warm kernel cache; yours will vary.

**The one-sentence pitch:** a MuJoCo-solved Franka arm picks up a VBD-solved
cable and places it elsewhere. Two different solvers run in the same scene,
coupled through a proxy. The simulation is headless and many worlds run in
parallel on the GPU. You play it back in the browser afterwards.

Demo highlights for the audience:

- coupling two solvers
- task control through keyframes and IK 
- parallelizing worlds
- running headless and visualizing locally

---

## 0. Before you start

```bash
uv sync                      # one-time setup
uv run main.py --help        # three subcommands: simulate, play, clean
```

- Have a browser ready. Playback is served as a local web page.
- The first `simulate` run downloads the Franka asset and compiles Warp
  kernels, so it is slow. **Do a warm-up run before the audience arrives:**
  `uv run main.py simulate --quiet`. (Cold, with no kernel cache, this takes
  about 45 s: roughly 11 s setup and 32 s compiling kernels. Warm, it takes 16 s.)

---

## 0b. First demo: a single arm (2 min, run takes ~16 s warm)

Start with the simplest case before explaining anything: one arm, one cable.

```bash
uv run main.py simulate --sim.num-worlds 1 --play
```

Open the printed URL and let the 7 s pick-and-place play through.

**Say:** this is the whole task: the arm picks up the cable and puts it
somewhere else. Everything after this is how it works and how to scale it.
Steady speed is about 23 ms/frame (about 44 world-frames/s). A single world
barely uses the GPU, which is why section 4 gets so much more out of it.

**Note:** the first run with a new world count recompiles kernels (about 19 s
extra). Run `--sim.num-worlds 1` once during warm-up so this one is fast.

---

## 1. The big picture (2 min, no commands)

Open `sim.py` and show the three ideas.

| Piece          | Where                                       | Say                              |
| -------------- | ------------------------------------------- | -------------------------------- |
| Two solvers    | `_build_solver`                             | Separate arm and cable solvers.  |
| Proxy coupling | `SolverCoupledProxy.Proxy`                  | Two-way gripper–cable coupling.  |
| Task control   | `_keyframes`, `_update_targets`, `ik.IKSolver` | Keyframes → IK → joint targets. |

**Two solvers:** The arm uses `SolverMuJoCo` (articulated, good at joints and
PD control). The cable uses `SolverVBD` (good at thin, stiff, deformable rods).

**Proxy coupling:** Show
`SolverCoupledProxy.Proxy(source="mjc", destination="vbd", bodies=gripper)`.
The cable solver sees the gripper bodies as a proxy. The gripper moves the
cable, and the cable pushes back. `mode="lagged"` means the proxy lags by one step.

**Task control:** A keyframe table drives the hand target. IK turns it into
joint targets, and Warp kernels broadcast it to every world.

---

## 2. Simulate and record (2 min, run takes ~16 s)

```bash
uv run main.py simulate
```

**Point out in the output:**

- The header line shows `device`, `worlds=4`, `bodies`, and `frames=420 (7.0s sim time)`.
- The progress bar shows the first frame is slow (kernel compile), then it speeds up.
- A `Timing:` line splits the run into `setup` (2.3 s), `first_frame`
  (0.8 s with a warm cache) and `steady` (about 24 ms/frame, 165 world-frames/s).
- The end of the run prints world-frames/s and the **per-world placement error**
  (roughly 1–6 cm with defaults; it varies run to run).
- `Recording written to recordings/franka_cable.viser`.

**Say:** nothing is rendered during simulation. The viewer is only used as a
recorder, so this works on a headless GPU box.

---

## 3. Play it back (2 min, no simulation)

```bash
uv run main.py play
```

Open the printed URL in a browser. Press Ctrl+C in the terminal to stop.

**Walk through the 7 s task in the viewer (matches `_keyframes`):**

| Time      | Phase                              |
| --------- | ---------------------------------- |
| 0–1 s     | Move above the cable, gripper open |
| 1–1.5 s   | Descend                            |
| 1.5–2.5 s | Grasp (fingers close)              |
| 2.5–3.5 s | Lift                               |
| 3.5–4.5 s | Transport to the place target      |
| 4.5–5.5 s | Lower and settle                   |
| 5.5–6.5 s | Release                            |
| 6.5–7 s   | Retreat                            |

**Point out:** the cable sags and swings while it is carried. That is the VBD
solver reacting to the MuJoCo-driven gripper through the proxy. Several arms
are visible because each world has its own arm and cable. The default
`--sim.world-spacing` is 0.5 m, so neighbouring arms sit close together and
may overlap. That is harmless: the worlds never interact, and the spacing is
only an offset applied when recording.

Optional: use a fixed port, which is handy for SSH forwarding.

```bash
uv run main.py play --port 8000
```

---

## 4. Scale: many parallel worlds (1–2 min, run takes ~35 s)

```bash
uv run main.py simulate --sim.num-worlds 16 --play
```

**Say:** each world is a full copy of the scene. All worlds are simulated at the
origin, and `--sim.world-spacing` only offsets them visually. Compare the
`world-frames/s` figure with the 4-world run. Throughput should scale well
because the IK and the physics both run batched on the GPU. Measured: 4 worlds
gives about 165 world-frames/s, 16 worlds about 590 (3.6x for 4x the worlds;
27 ms/frame vs 24 ms/frame). The first frame is slower with a new world count
(about 19 s) because Warp compiles kernels for the new size.

Other options:

```bash
uv run main.py simulate --sim.steps 120          # only the first 120 frames
uv run main.py simulate --sim.device cpu --sim.num-worlds 1   # no GPU needed, slow
uv run main.py simulate --sim.world-spacing 1.5   # spread them out again
```

**CPU vs GPU.** Compare one world on the CPU with 16 worlds on the GPU:

```bash
uv run main.py simulate --sim.device cpu --sim.num-worlds 1 --sim.steps 60
uv run main.py simulate --sim.num-worlds 16
```

| Run               | Steady ms/frame | World-frames/s |
| ----------------- | --------------- | -------------- |
| 1 world, CPU      | ~104            | ~9.6           |
| 1 world, GPU      | ~23             | ~44            |
| 16 worlds, GPU    | ~27             | ~590           |

**Say:** 16 worlds on the GPU is about 60x the CPU throughput. Most of that comes
from batching: 16 worlds cost barely more per frame than one. The CPU run takes
about 40 s the first time (12 s setup, 17 s compiling), and the CPU has no CUDA
graph, so use `--sim.steps 60` and do not run the full task there. Its short run
ends with a large placement error (about 27 cm) simply because it stops early.

---

## 4b. Timing: CUDA graph and kernel cache (3 min, runs take ~2 min total)

Two things dominate wall time. Show both with the `Timing:` line.

**CUDA graph.** By default the per-frame work (IK plus all physics substeps) is
captured once into a CUDA graph and replayed, which removes thousands of
kernel launches per frame.

```bash
uv run main.py simulate --sim.steps 120                      # graph on (default)
uv run main.py simulate --sim.steps 120 --sim.no-cuda-graph  # eager launches
```

| Run         | Steady ms/frame | World-frames/s |
| ----------- | --------------- | -------------- |
| graph on    | ~24             | ~165           |
| graph off   | ~100            | ~40            |

**Say:** about 4x faster, with identical physics. The graph needs an even
`--sim.substeps` because the two state buffers are swapped each substep and the
graph must end where it started. Graphs only apply on CUDA devices.

**Kernel cache.** Warp compiles kernels the first time it sees them and caches
the binaries on disk.

```bash
uv run main.py clean --keep-assets
uv run main.py simulate --sim.steps 60     # cold cache
uv run main.py simulate --sim.steps 60     # warm cache
```

| Cache | setup | first_frame | steady ms/frame |
| ----- | ----- | ----------- | --------------- |
| cold  | ~10.6 s | ~31.7 s   | ~27             |
| warm  | ~2.3 s  | ~0.8 s    | ~24             |

**Say:** the cache only changes startup (about 40 s cold vs 3 s warm), not
steady-state speed. Do the cold run before the demo, not during it. Without the
graph, the cache matters just as much; with the graph, the steady state is the
only part that gets faster.

---

## 5. Change the task (2 min)

Show that the demo is configurable from the CLI through `SimConfig`, which tyro
exposes as `--sim.*` flags.

```bash
# Faster motion
uv run main.py simulate --sim.speed 2.0 --play

# Place the cable somewhere else
uv run main.py simulate --sim.place-x 0.3 --sim.place-y -0.2 --play
```

Check the printed placement error to see whether the task still succeeds.

---

## 6. Change the cable (2 min, runs take ~16 s each)

```bash
# Longer, more segments
uv run main.py simulate --sim.cable-segments 31 --sim.cable-length 0.45 --play

# Stiffer vs. floppier
uv run main.py simulate --sim.cable-bend-stiffness 5e-2 --play
uv run main.py simulate --sim.cable-bend-stiffness 5e-5 --play
```

**Say:** this is the point of using VBD for the cable. Bend stiffness, stretch
stiffness, density and segment count are all physical parameters. A floppier
cable swings more and ends up with a larger placement error. A very long cable
may not be graspable at all.

---

## 6b. Domain randomization (2 min, runs take ~20 s each)

Every world can get its own random parameters, so one run covers many variations
of the task. This is where many parallel worlds pay off beyond raw speed.

```bash
uv run main.py simulate --sim.rand.all --play                  # every parameter, default ranges
uv run main.py simulate --sim.rand.friction 0.5                # only cable friction, +-50%
uv run main.py simulate --sim.rand.all --sim.rand.timing 0     # everything except task timing
uv run main.py simulate --sim.rand.all --sim.seed 7            # a different draw
```

| Flag (`--sim.rand.<name>`) | Randomizes                                     | Default range |
| -------------------------- | ---------------------------------------------- | ------------- |
| `friction`                 | cable friction coefficient                     | +-30%         |
| `contact-ke`               | cable contact stiffness and damping            | +-20%         |
| `cable-mass`               | cable mass and inertia                         | +-30%         |
| `arm-gains`                | Franka arm PD gains                            | +-20%         |
| `cable-pos`                | cable start position (x, y); the grasp follows | +-3 cm        |
| `place-pos`                | place target (x, y)                            | +-5 cm        |
| `timing`                   | task speed                                     | +-10%         |

**Say:** each value is a uniform half-range around nominal, drawn per world from
`--sim.seed`. Unset means off, or the default range if `--sim.rand.all` is given;
`0` always switches a parameter off. Relative ranges must be below 1. The draw
order is fixed, so turning on one parameter never changes the samples of
another. The scales are written into the model arrays before the solvers are
built (`_randomize_model`), and the pick and place keyframes are shifted per
world (`_sample_randomization`).

**Point out:**

- The header prints the active half-ranges (`Domain randomization (half-ranges)`).
- The per-world placement errors now differ (one `--sim.rand.all` run gave
  about 1.7 to 4.7 cm across 4 worlds).
- Each world runs at its own speed because of `timing`, so the run length follows
  the slowest world: it can be longer or shorter than the nominal 420 frames
  (438 and 410 in two recorded runs).
- The slide after the table is a recording of two real runs (`--sim.rand.all`, then
  `--sim.seed 7`): same flags, different per-world errors.
- In the viewer the arms visibly pick up the cable at slightly different spots
  and drop it at different places.

**Caveats:** cable geometry, bend and stretch stiffness, cable yaw and the ground
material are not randomized yet (see the README). The effect size of each
parameter on the outcome has not been measured. Runs with the same seed use the
same parameters but are not bit-for-bit identical.

---

## 7. Solver and coupling tuning (1–2 min, runs take 15–28 s each)

```bash
uv run main.py simulate --sim.substeps 20 --sim.mujoco-iterations 150 --sim.vbd-iterations 30
uv run main.py simulate --sim.coupling-iterations 2
```

**Say:** more substeps and iterations mean better accuracy and slower runs.
`coupling-iterations` controls how many times the two solvers exchange state
within a step. Measured steady cost per frame: default 24 ms; 20 substeps with
150/30 iterations 53 ms (2.2x); 2 coupling iterations 39 ms (1.6x).

Show where the time goes:

```bash
uv run main.py simulate --sim.profile
```

This prints Warp's per-kernel GPU timing table. The first frame is excluded
because it compiles kernels.

---

## 8. Remote machine workflow (optional, 1 min)

```bash
# On the remote machine
uv run main.py simulate --quiet
uv run main.py play --port 39095

# On your laptop
ssh -L 39095:127.0.0.1:39095 user@remote
# then open the printed URL (http://127.0.0.1:39095/?playbackPath=...)
```

Or copy the `.viser` file to any machine that has the project and run `play` there.

---

## 9. Clean up (30 s)

```bash
uv run main.py clean --keep-assets   # clear Warp kernel caches only (keeps the Franka asset)
uv run main.py clean                 # also delete the downloaded Franka asset
```

Warn the audience that the next `simulate` will recompile and may re-download.

---

## Talking points and caveats

- **Placement error** is the horizontal distance from the cable centroid to the
  place target. It is computed on the GPU by two Warp kernels, `cable_centroid`
  and `placement_error`. Roughly 1–6 cm is normal with defaults, and runs are not bit-for-bit reproducible.
- `--sim.steps` counts frames. The default is the full 7 s task (420 frames at 60 fps).
  Larger values hold the final pose.
- While simulating, the recorder starts a viser server on port 8080 (or the next free port if taken;
  tested).
- `play` calls a private Newton method (`ViewerViser._serve_viser_recording`),
  so a Newton upgrade may break it.
- The arm is gravity compensated, so the PD targets only fight contact.

## Time budget

| Section                     | Talk   | Simulation |
| --------------------------- | ------ | ---------- |
| 0 Setup and warm-up         | 1 min  | 16 s       |
| 0b Single arm               | 2 min  | 16 s       |
| 1 Big picture               | 2 min  | none       |
| 2 Simulate                  | 2 min  | 16 s       |
| 3 Play back                 | 2 min  | none       |
| 4 Scale (incl. CPU run)     | 3 min  | ~75 s      |
| 4b Graph and cache          | 3 min  | ~2 min     |
| 5 Task (2 runs)             | 2 min  | 26 s       |
| 6 Cable (3 runs)            | 2 min  | 47 s       |
| 6b Domain randomization     | 2 min  | ~20 s      |
| 7 Solver tuning and profile | 2 min  | 65 s       |
| 8–9 Remote, clean up        | 1.5 min| ~16 s      |
| **Total**                   | ~24 min| ~7.5 min   |

Plus playback and questions: about 31 minutes, just over a 30 minute slot. Drop section 7, 4b or 6b if you are running behind.
Every command in this script was run and completed without errors.

## Suggested demo order if time is short (5 min)

1. Section 1 (the big picture, 1 min)
2. Section 2 (simulate)
3. Section 3 (play back)
4. Section 6, one cable variant, or section 6b (`--sim.rand.all`)
