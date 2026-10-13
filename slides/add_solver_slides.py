"""Insert the solver-background slides into the demo deck.

    uvx --from python-pptx python slides/add_solver_slides.py in.pptx slides-<timestamp>-<message>.pptx

Adds four slides after "Two solvers, one scene": Newton's solver lineup (table), SolverMuJoCo,
SolverKamino, and solver coupling (proxy vs ADMM). Content comes from the Newton docs
(solvers/index, solvers/mujoco, solvers/kamino, concepts/coupling). The slides reuse the deck's
own title, bullet and table styling by cloning shapes from existing slides. Refuses to run on a
deck that already has them.
"""

import argparse
from pathlib import Path

from pptx import Presentation
from deckkit import Kit, title_of

AFTER = "Two solvers, one scene"
FIRST = "Newton's solvers"

TABLE = {
    "cols": [2.6, 2.6, 2.7, 4.0],
    "rows": [
        ("Solver", "Coordinates", "Handles", "Notes"),
        ("SolverMuJoCo", "generalized", "rigid, articulated", "MuJoCo Warp; our arm"),
        ("SolverFeatherstone", "generalized", "rigid, particles, soft", "basic differentiability"),
        ("SolverXPBD", "maximal", "rigid, particles, cloth", "implicit; soft bodies experimental"),
        ("SolverSemiImplicit", "maximal", "rigid, particles, soft", "basic differentiability"),
        ("SolverVBD", "maximal", "rigid, particles, cloth, soft", "implicit, experimental; our cable"),
        ("SolverKamino", "maximal", "rigid, articulated", "kinematic loops; experimental"),
        ("SolverStyle3D", "-", "particles, cloth", "no joints"),
        ("SolverImplicitMPM", "-", "particles", "no rigid bodies or joints"),
    ],
}

MUJOCO = [
    "Wraps MuJoCo Warp behind Newton's solver interface: GPU, many worlds",
    "Articulations in generalized coordinates: the best fit for a robot arm",
    "Defaults to the implicitfast integrator for stability with stiff PD gains",
    "use_mujoco_contacts=False feeds in Newton's collision pipeline instead (we do this)",
    "All worlds must have identical entity counts (why we pad the cable)",
    "No ROD joints, cloth, particles or soft bodies; non-convex meshes are convex-hulled",
]
KAMINO = [
    "Rigid mechanisms in maximal coordinates: kinematic loops, joint limits, hard frictional contacts",
    "Two backends: padmm (default, robust) and dvi (faster, less accurate with many active contacts)",
    "Per-DoF actuation, armature, damping and Coulomb friction",
    "Not for particles or deformables",
    "Experimental (BETA 1): the API and behavior may change without notice",
    "Not used in this demo; worth a look if closed chains matter",
]
PROXY = [
    "The source solver owns the real body; the destination sees a proxy with scaled inertia",
    "mode=\"lagged\": rewind the proxy by the last feedback, then step (our choice)",
    "mode=\"staggered\": use the source's current state directly",
    "mass_scale and proxy_relaxation set the stability",
    "Up to two entries; supports MPM transfer proxies",
]
ADMM = [
    "Symmetric: interface rows between bodies or particles owned by different solvers",
    "Cross-solver BALL, FIXED and REVOLUTE joints, body-particle attachments, contacts",
    "A fixed iteration count (graph-capture friendly); tune rho, gamma and baumgarte",
    "More parameters and fewer supported row types than proxy coupling",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    if args.out.resolve() == args.deck.resolve():
        ap.error("out must differ from deck (keep the original)")

    prs = Presentation(args.deck)
    titles = [title_of(s) for s in prs.slides]
    if FIRST in titles:
        ap.error(f"deck already has the {FIRST!r} slide")
    if AFTER not in titles:
        ap.error(f"no slide titled {AFTER!r}")
    kit = Kit(prs)

    s1 = kit.new_slide(FIRST)
    kit.table(s1, TABLE["cols"], TABLE["rows"], 0.7, 1.5, name="solvers")
    kit.bullets(s1, ["Pick the coordinate system first: generalized for robots, maximal for the rest. "
                     "Experimental: VBD and Kamino."], 0.7, 5.85, 11.9, 0.8, size=16, name="takeaway", plain=True)
    kit.bullets(kit.new_slide("SolverMuJoCo: the arm"), MUJOCO, 0.7, 1.7, 11.9, 4.6, size=20)
    kit.bullets(kit.new_slide("SolverKamino: for closed chains"), KAMINO, 0.7, 1.7, 11.9, 4.6, size=20)
    s4 = kit.new_slide("Coupling: proxy vs ADMM")
    kit.bullets(s4, PROXY, 0.7, 1.6, 5.8, 4.8, heading="Proxy (our demo)", size=17, name="proxy")
    kit.bullets(s4, ADMM, 6.85, 1.6, 5.8, 4.8, heading="ADMM", size=17, name="admm")
    kit.bullets(s4, ["Experimental API: it may change without notice."], 0.7, 6.35, 11.9, 0.4,
                size=14, name="note", plain=True)

    kit.move_new_after(prs, titles.index(AFTER), 4)
    prs.save(args.out)
    print(f"saved {args.out}: {len(prs.slides)} slides")


if __name__ == "__main__":
    main()
