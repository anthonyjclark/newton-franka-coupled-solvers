# Slide media

Scripts that generate the media for the demo deck. The deck (`*.pptx`) and the
generated files are not tracked in git; rebuild them from here. Run everything from
anywhere (the scripts `cd` to the project root).

| Media                 | Script                | Output (ignored)                 | Notes                                                  |
| ---                   | ---                   | ---                              | ---                                                    |
| Terminal GIFs         | `make_gifs.sh`        | `slides/gifs/*.gif`              | Records real runs (`record.py`), renders (`render.py`) |
| Simulation videos     | `make_videos.sh`      | `slides/videos/*.mp4` + `.viser` | Uses `simulate --sim.video`; needs ffmpeg              |
| Video slides in deck  | `add_videos.py`       | a new `.pptx`                    | Inserts the videos after the matching slides           |

Both `make_*` scripts take an optional output directory as their first argument.

```bash
slides/make_gifs.sh                  # real simulation runs, several minutes
slides/make_videos.sh                # about 2-3 min
uvx --from python-pptx python slides/add_videos.py slides.pptx slides-video.pptx
```

`add_videos.py` places each video slide after the slide with a given title ("First demo:
a single arm", "Recording: 16 worlds", "Change the task", "Change the cable", "Recording:
randomization"), reuses the "Recording:" slide layout, extracts poster frames with ffmpeg,
and refuses to run on a deck that already has "Video:" slides or to overwrite its input.
GIFs are inserted into the deck by hand (no script places them).

The command lists in `make_gifs.sh` were reconstructed from the slide captions and
`script.md`, and the script itself has not been run end to end, so check the commands
against the slides before regenerating.
