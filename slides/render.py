"""render.py name -> name.gif. Replays a recording through a terminal emulator."""
import json, sys
import pyte
from PIL import Image, ImageDraw, ImageFont

name = sys.argv[1]
MAXDUR = float(sys.argv[2]) if len(sys.argv) > 2 else 18.0  # target seconds of run time in the GIF
data = json.load(open(f"{name}.json"))
COLS, ROWS = data["cols"], data["rows"]
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15)
BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 15)
CW, CH, PAD, BAR = 9, 19, 14, 30
W, H = COLS * CW + 2 * PAD, ROWS * CH + 2 * PAD + BAR
BG, FG, DIM = (24, 26, 31), (224, 227, 232), (128, 134, 144)
PALETTE = {"black": (24, 26, 31), "red": (240, 113, 120), "green": (118, 185, 0), "brown": (255, 203, 107),
           "blue": (130, 170, 255), "magenta": (199, 146, 234), "cyan": (137, 221, 255), "white": FG, "default": FG}

total_real = sum(s["dur"] for s in data["segments"])
speed = max(1.0, total_real / MAXDUR)

# timeline of (gif_time, text)
timeline, t = [], 0.0
for i, seg in enumerate(data["segments"]):
    t += 0.5 if i == 0 else 0.4
    for ch in "$ " + seg["cmd"]:
        timeline.append((t, ch)); t += 0.035
    t += 0.5
    timeline.append((t, "\r\n"))
    t += 0.15
    for te, txt in seg["events"]:
        timeline.append((t + te / speed, txt))
    t += seg["dur"] / speed
    if i < len(data["segments"]) - 1:
        t += 2.5  # hold the result, then clear for the next command
        timeline.append((t, "\x1b[2J\x1b[H"))
end = t + 3.0

screen = pyte.Screen(COLS, ROWS)
stream = pyte.Stream(screen)

def draw(show_speed):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, BAR], fill=(36, 39, 46))
    for k, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([PAD + k * 20, 9, PAD + k * 20 + 12, 21], fill=c)
    if show_speed:
        txt = f"{speed:.1f}x speed"
        d.text((W - PAD - len(txt) * 8, 8), txt, font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 13), fill=PALETTE["green"])
    cur = screen.cursor
    for y in range(ROWS):
        line = screen.buffer[y]
        for x in range(COLS):
            c = line[x]
            if c.data == " ":
                continue
            col = PALETTE.get(c.fg, None)
            if col is None:
                try:
                    col = tuple(int(c.fg[i:i + 2], 16) for i in (0, 2, 4))
                except Exception:
                    col = FG
            if c.fg == "default" and y < 0:
                col = FG
            d.text((PAD + x * CW, BAR + PAD + y * CH), c.data, font=BOLD if c.bold else FONT, fill=col)
    if int(T * 2) % 2 == 0 or T > end - 3:
        d.rectangle([PAD + cur.x * CW, BAR + PAD + cur.y * CH + 2, PAD + cur.x * CW + CW - 1, BAR + PAD + cur.y * CH + CH - 2], fill=(200, 205, 212))
    return im

FPS = 10
frames, durs, last, idx, T = [], [], None, 0, 0.0
while T <= end:
    while idx < len(timeline) and timeline[idx][0] <= T:
        stream.feed(timeline[idx][1]); idx += 1
    # colour hints: dim comment-ish lines are left as-is; render
    im = draw(speed > 1.05)
    key = im.tobytes()
    if key == last:
        durs[-1] += 1000 // FPS
    else:
        frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=256)); durs.append(1000 // FPS); last = key
    T += 1 / FPS
durs[-1] += 1500
frames[0].save(f"{name}.gif", save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True, disposal=1)
print(name, W, H, len(frames), "frames", f"speed={speed:.1f}x", f"{sum(durs)/1000:.1f}s")
