#!/usr/bin/env bash
# Render an .mp4 for each visual `simulate` variant used in the demo (see script.md).
# Usage: ./make_videos.sh [outdir]      (default: videos/)
set -euo pipefail
out=${1:-videos}
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
run randomized     --sim.num-worlds 8 --sim.rand.all
