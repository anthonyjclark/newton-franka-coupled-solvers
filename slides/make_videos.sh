#!/usr/bin/env bash
# Render an .mp4 for each visual `simulate` variant used in the demo (see script.md).
# Usage: slides/make_videos.sh [outdir]      (default: slides/videos/)
# Run from anywhere; commands execute at the project root.
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:-slides/videos}
mkdir -p "$out"
run() {  # run <name> <simulate args...>
  name=$1; shift
  echo "== $name: simulate $*"
  uv run main.py simulate --quiet --sim.no-verbose \
    --sim.output "$out/$name.viser" --sim.video "$out/$name.mp4" "$@" > /dev/null
}
run single-arm     --sim.num-worlds 1
run multi-world    --sim.num-worlds 16
run fast           --sim.num-worlds 1 --sim.speed 2.0
run place-target   --sim.num-worlds 1 --sim.place-x 0.3 --sim.place-y -0.2
run long-cable     --sim.num-worlds 1 --sim.cable-segments 31 --sim.cable-length 0.45
run stiff-cable    --sim.num-worlds 1 --sim.cable-bend-stiffness 5e-2
run soft-cable     --sim.num-worlds 1 --sim.cable-bend-stiffness 5e-5
run randomized     --sim.num-worlds 8 --sim.rand.all --sim.rand.cable-pos 0.10 --sim.rand.place-pos 0.15
run randomized-expensive --sim.num-worlds 8 --sim.rand.all --sim.rand.expensive --sim.rand.cable-pos 0.10 --sim.rand.place-pos 0.15
