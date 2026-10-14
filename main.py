"""CLI for the coupled Franka + cable demo.

uv run main.py simulate --sim.num-worlds 8 --sim.device cuda:0 --play
uv run main.py play recordings/franka_cable.viser
uv run main.py clean
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, ClassVar

import tyro

from sim import CoupledFrankaCable, SimConfig


def play(recording: Path, port: int = 0) -> None:
    """Serve a .viser recording in the browser until Ctrl+C (port 0 = pick a free one).

    The file is re-read on every request, so re-running ``simulate`` and refreshing
    the page shows the new recording without restarting the server.
    """
    if not recording.is_file():
        raise FileNotFoundError(f"recording not found: {recording}")
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from newton.viewer import ViewerViser

    recording = recording.resolve()
    client_dir = str(ViewerViser.get_viser_client_dir())

    class Handler(SimpleHTTPRequestHandler):
        extensions_map: ClassVar = {
            **SimpleHTTPRequestHandler.extensions_map,
            ".js": "application/javascript",
        }

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=client_dir, **kwargs)

        def do_GET(self):
            if self.path.split("?")[0] != f"/{recording.name}":
                return super().do_GET()
            try:
                data = recording.read_bytes()
            except OSError:
                return self.send_error(404, f"recording not found: {recording}")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/?playbackPath={recording.name}"
    print(f"Playback: {url}  (Ctrl+C to quit; refresh after re-simulating)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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
