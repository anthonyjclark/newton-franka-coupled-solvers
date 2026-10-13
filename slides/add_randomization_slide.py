"""Insert the "Expensive randomization" slide into the demo deck.

    uvx --from python-pptx python slides/add_randomization_slide.py in.pptx slides-<timestamp>-<message>.pptx

The slide clones the "Domain randomization" slide (command box + table) and goes right after
"Video: randomization" (or "Recording: randomization" if the video slide is missing). Run slides/add_videos.py afterwards so the matching video slide
follows it. It also sets the agenda slide's total time to match the script. Refuses to run on a deck that already has the slide.
"""

import argparse
import copy
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.util import Inches

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SRC, TITLE = "Domain randomization", "Expensive randomization"

CMD = [
    "$ uv run main.py simulate --sim.num-worlds 8 --sim.rand.all --sim.rand.expensive",
    "$ uv run main.py simulate --sim.rand.cable-bend 0.8   # one expensive parameter only",
]
ROWS = [
    ("Flag (--sim.rand.<name>)", "Randomizes", "Default range"),
    ("expensive", "enables every row below", ""),
    ("cable-length", "cable length", "±20%"),
    ("cable-radius", "cable radius (re-seated on the ground)", "±20%"),
    ("cable-segments", "segment count", "±4 segments"),
    ("cable-bend", "bend stiffness and damping", "±50%"),
    ("cable-stretch", "stretch stiffness", "±50%"),
    ("cable-yaw", "cable yaw about its centre (gripper does not follow)", "±0.4 rad"),
]


def title_of(slide) -> str:
    sp = next((s for s in slide.shapes if s.is_placeholder and s.placeholder_format.type == PP_PLACEHOLDER.TITLE), None)
    return sp.text_frame.text if sp is not None else ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    if args.out.resolve() == args.deck.resolve():
        ap.error("out must differ from deck (keep the original)")

    prs = Presentation(args.deck)
    slides = list(prs.slides)
    titles = [title_of(s) for s in slides]
    if TITLE in titles:
        ap.error(f"deck already has the {TITLE!r} slide")
    # Goes after the cheap-randomization video if the deck has it, else after the recording.
    AFTER = "Video: randomization" if "Video: randomization" in titles else "Recording: randomization"
    for t in (SRC, AFTER):
        if t not in titles:
            ap.error(f"no slide titled {t!r}")

    src = slides[titles.index(SRC)]
    new = prs.slides.add_slide(src.slide_layout)
    for ph in list(new.placeholders):
        ph._element.getparent().remove(ph._element)
    for shape in src.shapes:
        new.shapes._spTree.append(copy.deepcopy(shape._element))

    shapes = {s.name: s for s in new.shapes}
    shapes["Text 0"]._element.findall(f".//{A}t")[0].text = TITLE
    cmd = shapes["cmd"]
    paras = cmd._element.findall(f".//{A}p")
    runs = paras[1].findall(f"{A}r")  # templates: gray "$ ", dark text, blue flag, orange value
    gray, dark, blue, orange = runs[0], runs[1], runs[3], runs[-1]

    def fill(p, line):
        for r in p.findall(f"{A}r"):
            p.remove(r)
        end = p.find(f"{A}endParaRPr")
        code, _, comment = line.partition("   #")
        pieces = [(gray, "$ ")]
        for tok in code[2:].split(" "):
            kind = blue if tok.startswith("--") else orange if tok.replace(".", "").isdigit() else dark
            pieces += [(dark, " ")] if len(pieces) > 1 else []
            pieces.append((kind, tok))
        if comment:
            pieces.append((gray, "   #" + comment))
        for tpl, text in pieces:
            r = copy.deepcopy(tpl)
            r.findall(f"{A}t")[0].text = text
            end.addprevious(r) if end is not None else p.append(r)

    for p, text in zip(paras, CMD):
        fill(p, text)
    for p in paras[len(CMD):]:
        p.getparent().remove(p)
    shapes["cmd bg"].height = Inches(0.8)
    cmd.height = Inches(0.56)
    tbl = shapes["randomization"]
    tbl.top = Inches(2.75)

    t = tbl._element.find(f".//{A}tbl")
    trs = t.findall(f"{A}tr")
    assert len(trs) == len(ROWS), (len(trs), len(ROWS))
    for tr, row in zip(trs, ROWS):
        for tc, text in zip(tr.findall(f"{A}tc"), row):
            runs = tc.findall(f".//{A}r")
            if runs:
                runs[0].findall(f"{A}t")[0].text = text
            elif text:  # empty source cell: reuse the run from a sibling in the same row
                raise SystemExit("unexpected empty cell in the template table")
            if not text and runs:
                runs[0].findall(f"{A}t")[0].text = ""

    # Keep the agenda slide's total in step with the script's time budget (~28 min talk + ~7.5 min runs).
    for sl in slides:
        for sh in sl.shapes:
            if sh.name == "stat talk plus simulation":
                sh._element.findall(f".//{A}t")[0].text = "~36 min"

    lst = prs.slides._sldIdLst
    sid = list(lst)[-1]
    lst.remove(sid)
    list(lst)[titles.index(AFTER)].addnext(sid)
    prs.save(args.out)
    print(f"saved {args.out}: {len(prs.slides)} slides")


if __name__ == "__main__":
    main()
