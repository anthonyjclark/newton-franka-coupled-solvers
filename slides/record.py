"""Run real commands in a pty and save timestamped output: record.py name 'cmd1' 'cmd2' ..."""
import fcntl, json, os, pty, select, struct, subprocess, sys, termios, time
COLS, ROWS = 108, 16
name, cmds = sys.argv[1], sys.argv[2:]
env = dict(os.environ, TERM="xterm-256color", COLUMNS=str(COLS), LINES=str(ROWS), PYTHONUNBUFFERED="1")
segments = []  # each: {"cmd":..., "events":[[t,str],...], "dur":float}
for cmd in cmds:
    m, sl = os.openpty()
    fcntl.ioctl(m, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    p = subprocess.Popen(["bash", "-c", cmd], stdin=sl, stdout=sl, stderr=sl, env=env, close_fds=True, start_new_session=True)
    os.close(sl)
    t0 = time.perf_counter(); ev = []
    while True:
        r, _, _ = select.select([m], [], [], 0.05)
        if r:
            try:
                d = os.read(m, 65536)
            except OSError:
                break
            if not d:
                break
            ev.append([time.perf_counter() - t0, d.decode("utf-8", "replace")])
        elif p.poll() is not None:
            break
    p.wait(); os.close(m)
    segments.append({"cmd": cmd, "events": ev, "dur": time.perf_counter() - t0, "rc": p.returncode})
json.dump({"cols": COLS, "rows": ROWS, "segments": segments}, open(f"{name}.json", "w"))
print(name, [round(s["dur"], 1) for s in segments], [s["rc"] for s in segments])
