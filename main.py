"""CLI for the coupled Franka + cable demo.

uv run main.py simulate --sim.num-worlds 8 --sim.device cuda:0 --play
uv run main.py play recordings/franka_cable.viser
uv run main.py clean
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import tyro

from sim import CoupledFrankaCable, SimConfig


def play(recording: Path, port: int = 0) -> None:
    """Serve a .viser recording in the browser until Ctrl+C (port 0 = pick a free one)."""
    if not recording.is_file():
        raise FileNotFoundError(f"recording not found: {recording}")
    import http.server

    from newton.viewer import ViewerViser

    # Newton always binds an ephemeral port; force the requested one for this call.
    http_server = http.server.HTTPServer

    class FixedPortServer(http_server):
        def __init__(self, address, handler):
            super().__init__((address[0], port), handler)

    http.server.HTTPServer = FixedPortServer
    try:
        url = ViewerViser._serve_viser_recording(str(recording))
    finally:
        http.server.HTTPServer = http_server
    print(f"Playback: {url}  (Ctrl+C to quit)", flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


@dataclass
class Simulate:
    """Run and record headless simulation."""

    sim: SimConfig = field(default_factory=SimConfig)
    play: bool = False
    """Serve the recording for playback once the simulation finishes."""
    quiet: bool = False
    """Suppress Warp's info output (init banner, kernel compile/load messages)."""
    port: int = 0
    """Port for --play (0 = pick a free one)."""

    def run(self) -> None:
        if self.quiet:
            import warp as wp

            wp.config.log_level = wp.LOG_WARNING
        out = CoupledFrankaCable(self.sim).run()
        print(f"Recording written to {out}")
        if self.play:
            play(out, self.port)


@dataclass
class Play:
    """Play back an existing recording."""

    recording: tyro.conf.Positional[Path] = Path("recordings/franka_cable.viser")
    port: int = 0
    """Port to serve on (0 = pick a free one)."""

    def run(self) -> None:
        play(self.recording, self.port)


@dataclass
class Clean:
    """Clear Warp's compiled-kernel caches and Newton's downloaded assets."""

    keep_assets: bool = False
    """Keep Newton's downloaded asset cache (e.g. the Franka URDF)."""

    def run(self) -> None:
        import warp as wp

        wp.clear_kernel_cache()
        wp.clear_lto_cache()
        print("Cleared Warp kernel and LTO caches")
        if not self.keep_assets:
            from newton._src.utils.download_assets import _get_newton_cache_dir

            path = Path(_get_newton_cache_dir())
            shutil.rmtree(path, ignore_errors=True)
            print(f"Removed Newton asset cache {path}")


def main() -> None:
    sim_cmd = Annotated[Simulate, tyro.conf.subcommand("simulate")]
    play_cmd = Annotated[Play, tyro.conf.subcommand("play")]
    clean_cmd = Annotated[Clean, tyro.conf.subcommand("clean")]
    cmd = tyro.cli(sim_cmd | play_cmd | clean_cmd)
    try:
        cmd.run()
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
