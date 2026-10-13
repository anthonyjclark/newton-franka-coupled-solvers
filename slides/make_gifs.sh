#!/usr/bin/env bash
# Record real terminal runs and render each as an animated GIF for the slides.
# Usage: slides/make_gifs.sh [outdir]      (default: slides/gifs/)
# Needs uv (render.py runs with pyte + Pillow via uvx). Commands run at the project
# root. The command lists below are reconstructed from the slide captions and script.md.
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:-slides/gifs}
mkdir -p "$out"
gif() {  # gif <name> <command>...   (each command is one terminal "segment")
  name=$1; shift
  echo "== $name"
  python3 slides/record.py "$out/$name" "$@"
  uvx --with pyte --with pillow python slides/render.py "$out/$name"
}
gif simulate  'uv run main.py simulate'
gif scale     'uv run main.py simulate --sim.num-worlds 16'
gif cpugpu    'uv run main.py simulate --sim.device cpu --sim.num-worlds 1 --sim.steps 60' \
              'uv run main.py simulate --sim.num-worlds 16'
gif graph     'uv run main.py simulate --sim.steps 120' \
              'uv run main.py simulate --sim.steps 120 --sim.no-cuda-graph'
gif cache     'uv run main.py clean --keep-assets' \
              'uv run main.py simulate --sim.steps 60' \
              'uv run main.py simulate --sim.steps 60'
gif randomize 'uv run main.py simulate --sim.rand.all' \
              'uv run main.py simulate --sim.rand.all --sim.seed 7'
