"""Coupled Franka + cable pick-and-place (MuJoCo arm, VBD cable, proxy coupling).

Headless, multi-world version of the Newton Fundamentals "coupled manipulation"
lesson. The simulation runs without any rendering; every frame is written to a
``.viser`` recording that can be played back afterwards (see ``main.py``).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import newton
import newton.utils
import numpy as np
import warp as wp
from newton import ik
from newton.solvers import SolverMuJoCo, SolverVBD
from newton.solvers.experimental.coupled import SolverCoupled, SolverCoupledProxy
from tqdm import tqdm

FRANKA_Q = [
    -3.6802115e-03, 2.3901723e-02, 3.6804110e-03, -2.3683236e00,
    -1.2918962e-04, 2.3922248e00, 7.8549200e-01, 0.04, 0.04,
]  # fmt: skip
GRIPPER_DOWN = (1.0, 0.0, 0.0, 0.0)  # xyzw quaternion, fingers pointing down
GRIP_OPEN = 0.04
GRIP_CLOSE = 0.0
GRIP_FORCE = 1500.0
GRIP_STIFFNESS = 1000.0

N_PICK_KEYFRAMES = 4


@dataclass
class Randomization:
    """Per-world domain randomization. Each value is a uniform half-range around nominal.

    ``None`` means "off", or the default range if ``all`` is set; ``0`` always disables.
    Relative ranges must be below 1 (a factor of 1 - range would reach zero or go negative).
    """

    all: bool = False
    """Enable every parameter below at its default range (explicit values override)."""
    friction: float | None = None
    """Cable friction coefficient, relative (default 0.3 = +-30%)."""
    contact_ke: float | None = None
    """Cable contact stiffness (and damping), relative (default 0.2)."""
    cable_mass: float | None = None
    """Cable mass and inertia, relative (default 0.3)."""
    arm_gains: float | None = None
    """Franka arm PD gains, relative (default 0.2)."""
    cable_pos: float | None = None
    """Cable start position shift in x and y, metres (default 0.03). The grasp follows it."""
    place_pos: float | None = None
    """Place target shift in x and y, metres (default 0.05)."""
    timing: float | None = None
    """Task speed, relative (default 0.1 = tasks run 10% faster or slower)."""

    DEFAULTS = {  # noqa: RUF012
        "friction": 0.3, "contact_ke": 0.2, "cable_mass": 0.3, "arm_gains": 0.2,
        "cable_pos": 0.03, "place_pos": 0.05, "timing": 0.1,
    }  # fmt: skip

    def ranges(self) -> dict[str, float]:
        out = {}
        for name, default in self.DEFAULTS.items():
            v = getattr(self, name)
            out[name] = float(v) if v is not None else (default if self.all else 0.0)
        return out

    def validate(self) -> None:
        for name, v in self.ranges().items():
            if v < 0:
                raise ValueError(
                    f"--sim.rand.{name.replace('_', '-')} must be >= 0 (got {v})"
                )
            if name not in ("cable_pos", "place_pos") and v >= 1:
                raise ValueError(
                    f"--sim.rand.{name.replace('_', '-')} is relative and must be < 1 (got {v})"
                )


@dataclass
class SimConfig:
    """Everything that can be tuned from the command line."""

    # --- Simulation ---
    num_worlds: int = 4
    """Number of independent copies of the scene simulated in parallel."""
    steps: int | None = None
    """Number of frames to simulate. Default: the full pick-and-place task."""
    device: str = "cuda:0"
    """Warp device (e.g. cuda:0, cpu)."""
    fps: int = 60
    """Frame rate of the recording (one IK update + `substeps` physics steps per frame)."""
    substeps: int = 10
    """Physics substeps per frame."""
    ik_iterations: int = 24
    """Levenberg-Marquardt iterations per frame for the arm's IK."""
    # --- Cable ---
    cable_segments: int = 19
    cable_length: float = 0.38
    cable_radius: float = 0.005
    cable_density: float = 100.0
    cable_bend_stiffness: float = 5.0e-4
    cable_stretch_stiffness: float = 1.0e6
    cable_height: float = 0.256
    """Height (z) of the cable's center line above the world origin."""
    cable_x: float = 0.5
    """Cable center position along x (it lies along the x axis, y = 0)."""
    # --- Task ---
    place_x: float = 0.4
    place_y: float = 0.25
    """Where the cable gets dropped."""
    approach_height: float = 0.20
    """Height above the cable for the approach / transport waypoints."""
    speed: float = 1.0
    """Task time scale; >1 is faster (shorter keyframe durations)."""
    # --- Coupling / solvers ---
    mujoco_iterations: int = 100
    vbd_iterations: int = 20
    coupling_iterations: int = 1
    # --- Output ---
    world_spacing: float = 0.5
    """Visual spacing (m) between worlds in the viewer. Small values make neighbouring
    arms overlap, which is harmless: physics stays at the origin."""
    output: Path = Path("recordings/franka_cable.viser")
    video: Path | None = None
    """Also render the run to this video file (.mp4) with an offscreen OpenGL viewer (needs ffmpeg)."""
    video_size: tuple[int, int] = (1280, 720)
    """Video width and height in pixels (rounded down to even numbers)."""
    seed: int = 0
    rand: Randomization = field(default_factory=Randomization)
    verbose: bool = True
    cuda_graph: bool = True
    """Capture the per-frame work (IK + physics substeps) into a CUDA graph and replay it.
    Only used on CUDA devices; use --sim.no-cuda-graph to compare against eager launches."""
    profile: bool = False
    """Print Warp's per-kernel GPU timing table (first frame excluded: it compiles kernels)."""

    def validate(self) -> None:
        """Raise ValueError with a readable message for settings that cannot work."""
        positive = [
            "num_worlds", "fps", "substeps", "ik_iterations", "cable_radius", "cable_length", "cable_density",
            "cable_bend_stiffness", "cable_stretch_stiffness", "speed", "mujoco_iterations",
            "vbd_iterations", "coupling_iterations",
        ]  # fmt: skip
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(
                    f"--sim.{name.replace('_', '-')} must be > 0 (got {getattr(self, name)})"
                )
        if self.cable_segments < 2:
            raise ValueError(
                f"--sim.cable-segments must be >= 2 (got {self.cable_segments})"
            )
        if self.substeps % 2:
            raise ValueError(
                f"--sim.substeps must be even (got {self.substeps}): the state buffers are swapped every substep"
            )
        if self.steps is not None and self.steps < 0:
            raise ValueError(f"--sim.steps must be >= 0 (got {self.steps})")
        if self.cable_height <= self.cable_radius:
            raise ValueError(
                "--sim.cable-height must be above --sim.cable-radius (the ground sits at height - radius)"
            )
        try:
            wp.get_device(self.device)
        except (ValueError, RuntimeError) as e:
            raise ValueError(
                f"--sim.device {self.device!r} is not available: {e}"
            ) from None
        self.rand.validate()


# --------------------------------------------------------------------------
# Warp kernels
# --------------------------------------------------------------------------
@wp.kernel
def set_gripper_q(
    joint_q: wp.array2d[float], finger_pos: wp.array[float], idx0: int, idx1: int
):
    """IK only drives the arm; overwrite the two finger coordinates with the grip command."""
    world = wp.tid()
    joint_q[world, idx0] = finger_pos[world]
    joint_q[world, idx1] = finger_pos[world]


@wp.kernel
def cable_centroid(
    body_q: wp.array[wp.transform],
    bodies_per_world: int,
    cable_first_body: int,
    segments: int,
    centroid: wp.array[wp.vec3],
):
    """Average the cable segment positions of every world (one thread per segment)."""
    tid = wp.tid()
    world = tid // segments
    seg = tid % segments
    p = wp.transform_get_translation(
        body_q[world * bodies_per_world + cable_first_body + seg]
    )
    wp.atomic_add(centroid, world, p / float(segments))


@wp.kernel
def placement_error(
    centroid: wp.array[wp.vec3], target_xy: wp.array[wp.vec2], error: wp.array[float]
):
    """Horizontal distance between the cable centroid and each world's place target."""
    world = wp.tid()
    d = wp.vec2(centroid[world][0], centroid[world][1]) - target_xy[world]
    error[world] = wp.length(d)


# --------------------------------------------------------------------------
# Scene construction
# --------------------------------------------------------------------------
def _add_franka(builder: newton.ModelBuilder, base_z: float) -> None:
    builder.add_urdf(
        newton.utils.download_asset("franka_emika_panda") / "urdf/fr3_franka_hand.urdf",
        xform=wp.transform(wp.vec3(0.0, 0.0, base_z), wp.quat_identity()),
        floating=False,
        enable_self_collisions=False,
        parse_visuals_as_colliders=False,
        force_show_colliders=False,
    )
    builder.joint_q[: len(FRANKA_Q)] = FRANKA_Q
    builder.joint_target_q[: len(FRANKA_Q)] = FRANKA_Q


def _build_one_world(
    cfg: SimConfig, surface_z: float, contact_ke: float, contact_kd: float
):
    """Franka + cable for a single world. Returns the builder and local index ranges."""
    b = newton.ModelBuilder(gravity=-9.81)
    b.rigid_gap = 0.01
    SolverMuJoCo.register_custom_attributes(b)
    SolverVBD.register_custom_attributes(b, dahl_defaults_enabled=False)

    body0, joint0, shape0 = b.body_count, b.joint_count, b.shape_count
    _add_franka(b, surface_z)

    b.joint_target_ke[:7] = [400.0] * 7
    b.joint_target_kd[:7] = [80.0] * 7
    b.joint_target_ke[7:9] = [GRIP_STIFFNESS] * 2
    b.joint_target_kd[7:9] = [100.0] * 2
    b.joint_effort_limit[:4] = [87.0] * 4
    b.joint_effort_limit[4:7] = [12.0] * 3
    b.joint_effort_limit[7:9] = [GRIP_FORCE] * 2
    b.joint_armature[:7] = [1.0e-3] * 7
    b.joint_armature[7:9] = [0.0] * 2

    franka = {
        "bodies": list(range(body0, b.body_count)),
        "joints": list(range(joint0, b.joint_count)),
        "shapes": list(range(shape0, b.shape_count)),
    }

    # The arm is gravity compensated so the PD targets only fight the contact.
    gravcomp = b.custom_attributes["mujoco:gravcomp"]
    if gravcomp.values is None:
        gravcomp.values = {}
    for body in franka["bodies"]:
        gravcomp.values[body] = 1.0

    body0, joint0, shape0 = b.body_count, b.joint_count, b.shape_count
    cable_cfg = newton.ModelBuilder.ShapeConfig(
        density=cfg.cable_density,
        ke=contact_ke,
        kd=contact_kd,
        mu=1.0,
        margin=0.0,
        gap=0.01,
    )
    points, quats = newton.utils.create_straight_cable_points_and_quaternions(
        start=wp.vec3(cfg.cable_x - 0.5 * cfg.cable_length, 0.0, cfg.cable_height),
        direction=wp.vec3(1.0, 0.0, 0.0),
        length=cfg.cable_length,
        num_segments=cfg.cable_segments,
        twist_total=0.0,
    )
    b.add_rod(
        positions=points,
        quaternions=quats,
        radius=cfg.cable_radius,
        body_frame_origin="start",
        cfg=cable_cfg,
        stretch_stiffness=cfg.cable_stretch_stiffness,
        stretch_damping=1.0e-1,
        bend_stiffness=cfg.cable_bend_stiffness,
        bend_damping=2.0e-3 * cfg.cable_bend_stiffness,
        label="vbd_cable",
    )
    cable = dict(
        bodies=list(range(body0, b.body_count)),
        joints=list(range(joint0, b.joint_count)),
        shapes=list(range(shape0, b.shape_count)),
    )

    gripper = [
        i
        for i in franka["bodies"]
        if "hand" in b.body_label[i] or "finger" in b.body_label[i]
    ]
    if not gripper:
        raise RuntimeError("Could not locate Franka gripper bodies for proxy coupling")
    return b, franka, cable, gripper


def _offset(idx: list[int], by: int) -> list[int]:
    return [i + by for i in idx]


def _keyframes(cfg: SimConfig):
    """(duration, x, y, z, qx, qy, qz, qw, grip) waypoints -> (targets, cumulative times)."""
    cx, cy, cz = cfg.cable_x, 0.0, cfg.cable_height
    hover = cz + cfg.approach_height
    px, py = cfg.place_x, cfg.place_y
    q = GRIPPER_DOWN
    rows = [
        [1.0, cx, cy, hover, *q, GRIP_OPEN],  # move above cable
        [0.5, cx, cy, cz, *q, GRIP_OPEN],  # descend
        [1.0, cx, cy, cz, *q, GRIP_CLOSE],  # grasp
        [1.0, cx, cy, hover, *q, GRIP_CLOSE],  # lift
        [1.0, px, py, hover, *q, GRIP_CLOSE],  # transport
        [0.5, px, py, cz, *q, GRIP_CLOSE],  # lower
        [0.5, px, py, cz, *q, GRIP_CLOSE],  # settle
        [1.0, px, py, cz, *q, GRIP_OPEN],  # release
        [0.5, px, py, hover, *q, GRIP_OPEN],  # retreat
    ]
    poses = np.array(rows, dtype=np.float32)
    poses[:, 0] /= cfg.speed
    return poses[:, 1:], np.cumsum(poses[:, 0])


class CoupledFrankaCable:
    """Builds the multi-world scene and steps it headlessly, recording to a .viser file."""

    def __init__(self, cfg: SimConfig):
        cfg.validate()
        self.cfg = cfg
        self.device = wp.get_device(cfg.device)
        np.random.seed(cfg.seed)
        wp.rand_init(cfg.seed)

        self.contact_ke = 1.0e4
        self.contact_kd = 1.0e-5 * self.contact_ke
        self.surface_z = cfg.cable_height - cfg.cable_radius
        self.targets, self.key_times = _keyframes(cfg)
        self._sample_randomization()
        self.frame_dt = 1.0 / cfg.fps
        self.sim_dt = self.frame_dt / cfg.substeps
        self.graph = None
        t_setup = time.perf_counter()

        with wp.ScopedDevice(self.device):
            self._build_scene()
            self._randomize_model()
            self._build_solver()
            self._build_ik()
        self.setup_time = time.perf_counter() - t_setup

    # -- construction ------------------------------------------------------
    def _build_scene(self) -> None:
        cfg = self.cfg
        one, franka, cable, gripper = _build_one_world(
            cfg, self.surface_z, self.contact_ke, self.contact_kd
        )
        self.bodies_per_world = one.body_count
        self.cable_first_body = cable["bodies"][0]
        n_b, n_j, n_s = one.body_count, one.joint_count, one.shape_count

        scene = newton.ModelBuilder(gravity=-9.81)
        scene.rigid_gap = 0.01
        SolverMuJoCo.register_custom_attributes(scene)
        SolverVBD.register_custom_attributes(scene, dahl_defaults_enabled=False)
        scene.replicate(one, cfg.num_worlds)

        plane_cfg = newton.ModelBuilder.ShapeConfig(
            ke=self.contact_ke, kd=self.contact_kd, mu=1.0, margin=0.0, gap=0.01
        )
        shapes_before = scene.shape_count
        scene.add_ground_plane(
            height=self.surface_z, cfg=plane_cfg, label="cable_ground_plane"
        )
        self.ground_shapes = list(range(shapes_before, scene.shape_count))

        scene.color()
        self.model = scene.finalize(device=self.device)
        self.model.shape_material_ke.fill_(self.contact_ke)
        self.model.shape_material_kd.fill_(self.contact_kd)
        self.model.shape_material_mu.fill_(1.0)

        # Global index lists: world w owns bodies/joints/shapes [w*n, (w+1)*n).
        worlds = range(cfg.num_worlds)
        gather = lambda key, stride, src: [  # noqa: E731
            i
            for w in worlds
            for i in _offset(src[key] if isinstance(src, dict) else src, w * stride)
        ]
        self.franka_bodies = gather("bodies", n_b, franka)
        self.franka_joints = gather("joints", n_j, franka)
        self.franka_shapes = gather("shapes", n_s, franka)
        self.cable_bodies = gather("bodies", n_b, cable)
        self.cable_joints = gather("joints", n_j, cable)
        self.cable_shapes = gather("shapes", n_s, cable)
        self.gripper_bodies = gather(None, n_b, gripper)

    def _sample_randomization(self) -> None:
        """Draw every per-world random scale up front (fixed draw order, so enabling one
        parameter never changes the values of another)."""
        cfg, n = self.cfg, self.cfg.num_worlds
        self.rand_ranges = r = cfg.rand.ranges()
        u = np.random.default_rng(cfg.seed).uniform(-1.0, 1.0, size=(9, n))
        self.rand = {
            "friction": 1.0 + r["friction"] * u[0],
            "contact_ke": 1.0 + r["contact_ke"] * u[1],
            "cable_mass": 1.0 + r["cable_mass"] * u[2],
            "arm_gains": 1.0 + r["arm_gains"] * u[3],
            "timing": 1.0 + r["timing"] * u[4],
            "cable_dxy": r["cable_pos"] * u[5:7].T,  # (n, 2)
            "place_dxy": r["place_pos"] * u[7:9].T,  # (n, 2)
        }

        # Per-world keyframes: pick keyframes follow the cable, the rest the place target.
        self.world_targets = np.repeat(self.targets[None], n, axis=0)  # (n, K, 8)
        self.world_targets[:, :N_PICK_KEYFRAMES, 0:2] += self.rand["cable_dxy"][
            :, None, :
        ]
        self.world_targets[:, N_PICK_KEYFRAMES:, 0:2] += self.rand["place_dxy"][
            :, None, :
        ]
        self.place_xy = (
            np.array([cfg.place_x, cfg.place_y], dtype=np.float32)
            + self.rand["place_dxy"]
        )

    def _randomize_model(self) -> None:
        """Write the sampled scales into the model. Must run before the solvers are built."""
        model, n, rand = self.model, self.cfg.num_worlds, self.rand

        cable_shapes = np.asarray(self.cable_shapes).reshape(n, -1)
        cable_bodies = np.asarray(self.cable_bodies).reshape(n, -1)
        dofs_per_world = model.joint_dof_count // n
        arm_dofs = (
            np.arange(n)[:, None] * dofs_per_world + np.arange(7)[None, :]
        )  # first 7 = arm joints

        def apply(arr, idx, factor):
            host = arr.numpy()
            f = factor.reshape((n,) + (1,) * (host[idx].ndim - 1))
            host[idx] = host[idx] * f
            arr.assign(host)

        apply(model.shape_material_mu, cable_shapes, rand["friction"])
        apply(model.shape_material_ke, cable_shapes, rand["contact_ke"])
        apply(model.shape_material_kd, cable_shapes, rand["contact_ke"])
        apply(model.body_mass, cable_bodies, rand["cable_mass"])
        apply(model.body_inertia, cable_bodies, rand["cable_mass"])
        apply(model.body_inv_mass, cable_bodies, 1.0 / rand["cable_mass"])
        apply(model.body_inv_inertia, cable_bodies, 1.0 / rand["cable_mass"])
        apply(model.joint_target_ke, arm_dofs, rand["arm_gains"])
        apply(model.joint_target_kd, arm_dofs, rand["arm_gains"])

    def _shift_cable(self, state) -> None:
        """Translate every world's cable by its sampled (dx, dy)."""
        n = self.cfg.num_worlds
        idx = np.asarray(self.cable_bodies).reshape(n, -1)
        q = state.body_q.numpy()
        q[idx, 0:2] += self.rand["cable_dxy"][:, None, :].astype(q.dtype)
        state.body_q.assign(q)

    def _ground_pairs(self):
        dynamic = set(self.franka_shapes) | set(self.cable_shapes)
        ground = set(self.ground_shapes)
        pairs = [
            (int(a), int(b))
            for a, b in self.model.shape_contact_pairs.numpy()
            if ({int(a), int(b)} & dynamic) and ({int(a), int(b)} & ground)
        ]
        if not pairs:
            raise RuntimeError("No robot- or cable-ground contact pairs were generated")
        return wp.array(
            np.asarray(pairs, dtype=np.int32), dtype=wp.vec2i, device=self.device
        )

    def _build_solver(self) -> None:
        cfg, model = self.cfg, self.model
        self.control = model.control()
        self.state_0 = model.state()
        self.state_1 = model.state()
        newton.eval_fk(model, model.joint_q, model.joint_qd, self.state_0)
        newton.eval_fk(model, model.joint_q, model.joint_qd, self.state_1)
        for state in (self.state_0, self.state_1):
            self._shift_cable(state)

        self.collision_pipeline = newton.CollisionPipeline(
            model, broad_phase="explicit", shape_pairs_filtered=self._ground_pairs()
        )
        self.contacts = self.collision_pipeline.contacts()

        self.solver = SolverCoupledProxy(
            model=model,
            entries=[
                SolverCoupled.Entry(
                    name="mjc",
                    solver=lambda view: SolverMuJoCo(
                        model=view, solver="newton", integrator="implicitfast", cone="elliptic",
                        iterations=cfg.mujoco_iterations, ls_iterations=20,
                        use_mujoco_contacts=False, njmax=256 * cfg.num_worlds, nconmax=64 * cfg.num_worlds,
                    ),
                    bodies=self.franka_bodies,
                    joints=self.franka_joints,
                ),
                SolverCoupled.Entry(
                    name="vbd",
                    solver=lambda view: SolverVBD(
                        model=view, iterations=cfg.vbd_iterations, rigid_avbd_beta=1.0e2,
                        rigid_contact_k_start=1.0e3, rigid_contact_history=False,
                    ),
                    bodies=self.cable_bodies,
                    joints=self.cable_joints,
                ),
            ],
            coupling=SolverCoupledProxy.Config(
                proxies=[
                    SolverCoupledProxy.Proxy(
                        source="mjc",
                        destination="vbd",
                        bodies=self.gripper_bodies,
                        mass_scale=1.0,
                        mode="lagged",
                        collision_pipeline=lambda m: newton.CollisionPipeline(m, broad_phase="explicit"),
                        collide_interval=1,
                    )
                ],
                iterations=cfg.coupling_iterations,
            ),
        )  # fmt: skip
        self.solver.prepare_contacts(self.contacts)

    def _build_ik(self) -> None:
        model, n_worlds = self.model, self.cfg.num_worlds
        ik_builder = newton.ModelBuilder(gravity=-9.81)
        _add_franka(ik_builder, self.surface_z)
        ik_model = ik_builder.finalize(device=self.device)

        self.n_coords = n = ik_model.joint_coord_count
        self.ik_joint_q = wp.clone(model.joint_q.reshape((n_worlds, -1))[:, :n])
        self.control_target_q = self.control.joint_target_q.reshape((n_worlds, -1))
        self.place_xy_wp = wp.array(self.place_xy, dtype=wp.vec2, device=self.device)
        self.finger_pos = wp.full(n_worlds, GRIP_OPEN, dtype=float, device=self.device)

        hand = next(
            i for i, l in enumerate(ik_model.body_label) if l.endswith("fr3_hand")
        )
        t0 = self.world_targets[:, 0].astype(np.float32)
        self.ik_target_pos = wp.array(t0[:, 0:3], dtype=wp.vec3, device=self.device)
        self.ik_target_rot = wp.array(t0[:, 3:7], dtype=wp.vec4, device=self.device)

        lower = wp.clone(model.joint_limit_lower.reshape((n_worlds, -1))[:, :n])
        upper = wp.clone(model.joint_limit_upper.reshape((n_worlds, -1))[:, :n])
        self.ik_solver = ik.IKSolver(
            model=ik_model,
            n_problems=n_worlds,
            objectives=[
                ik.IKObjectivePosition(
                    link_index=hand,
                    link_offset=wp.vec3(0.0, 0.0, 0.107),
                    target_positions=self.ik_target_pos,
                ),
                ik.IKObjectiveRotation(
                    link_index=hand,
                    link_offset_rotation=wp.quat_identity(),
                    target_rotations=self.ik_target_rot,
                ),
                ik.IKObjectiveJointLimit(
                    joint_limit_lower=lower.flatten(),
                    joint_limit_upper=upper.flatten(),
                    weight=10.0,
                ),
            ],
            lambda_initial=0.05,
            jacobian_mode=ik.IKJacobianType.ANALYTIC,
        )

    # -- stepping ----------------------------------------------------------
    @property
    def task_frames(self) -> int:
        slowest = float(self.rand["timing"].min())
        return int(np.ceil(float(self.key_times[-1]) * self.cfg.fps / slowest))

    def _update_targets(self, t: float) -> None:
        """Interpolate every world's keyframes at its own (randomly scaled) task time."""
        kt, n = self.key_times, self.cfg.num_worlds
        tw = np.minimum(t * self.rand["timing"], float(kt[-1]) - 1.0e-6)  # (n,)
        i = np.searchsorted(kt, tw)  # (n,) segment index per world
        t_start = np.where(i > 0, kt[np.maximum(i - 1, 0)], 0.0)
        alpha = np.clip((tw - t_start) / np.maximum(kt[i] - t_start, 1.0e-6), 0.0, 1.0)[
            :, None
        ]
        tg, w = self.world_targets, np.arange(n)
        k = (1.0 - alpha) * tg[w, np.maximum(i - 1, 0)] + alpha * tg[
            w, i
        ]  # first segment: prev = tg[0]
        k = np.where((i > 0)[:, None], k, tg[w, i])
        k = k.astype(np.float32)
        wp.copy(
            self.ik_target_pos, wp.array(k[:, 0:3], dtype=wp.vec3, device=self.device)
        )
        wp.copy(
            self.ik_target_rot, wp.array(k[:, 3:7], dtype=wp.vec4, device=self.device)
        )
        wp.copy(self.finger_pos, wp.array(k[:, 7], dtype=float, device=self.device))

    def _capture_graph(self) -> None:
        """Capture one frame of IK + physics. Substeps is even, so state_0/state_1 end up
        where they started and the same graph can be replayed every frame."""
        with wp.ScopedCapture(device=self.device) as capture:
            self._frame_work()
        self.graph = capture.graph

    def _step_frame(self) -> None:
        if self.graph is not None:
            wp.capture_launch(self.graph)
        else:
            self._frame_work()

    def _frame_work(self) -> None:
        self.ik_solver.step(
            self.ik_joint_q, self.ik_joint_q, iterations=self.cfg.ik_iterations
        )
        wp.launch(
            set_gripper_q,
            dim=self.cfg.num_worlds,
            inputs=[
                self.ik_joint_q,
                self.finger_pos,
                self.n_coords - 2,
                self.n_coords - 1,
            ],
            device=self.device,
        )
        wp.copy(dest=self.control_target_q[:, : self.n_coords], src=self.ik_joint_q)
        for _ in range(self.cfg.substeps):
            self.state_0.clear_forces()
            self.collision_pipeline.collide(self.state_0, self.contacts)
            self.solver.step(
                self.state_0, self.state_1, self.control, self.contacts, self.sim_dt
            )
            newton.eval_ik(
                self.model, self.state_1, self.state_1.joint_q, self.state_1.joint_qd
            )
            self.state_0, self.state_1 = self.state_1, self.state_0

    def placement_errors(self) -> np.ndarray:
        """Per-world horizontal distance (m) from the cable centroid to the place target."""
        n, segs = self.cfg.num_worlds, self.cfg.cable_segments
        centroid = wp.zeros(n, dtype=wp.vec3, device=self.device)
        error = wp.zeros(n, dtype=float, device=self.device)
        wp.launch(
            cable_centroid,
            dim=n * segs,
            inputs=[
                self.state_0.body_q,
                self.bodies_per_world,
                self.cable_first_body,
                segs,
                centroid,
            ],
            device=self.device,
        )
        wp.launch(
            placement_error,
            dim=n,
            inputs=[centroid, self.place_xy_wp, error],
            device=self.device,
        )
        return error.numpy()

    def _open_video(self):
        """Return (offscreen viewer, ffmpeg process) for ``cfg.video``."""
        cfg = self.cfg
        if shutil.which("ffmpeg") is None:
            raise ValueError("--sim.video needs ffmpeg on PATH")
        import pyglet

        pyglet.options["headless"] = True  # EGL: no display needed
        w, h = (v // 2 * 2 for v in cfg.video_size)
        gl = newton.viewer.ViewerGL(width=w, height=h, headless=True)
        gl.set_model(self.model)
        gl.set_world_offsets((cfg.world_spacing, cfg.world_spacing, 0.0))
        # Pull the camera back so the whole grid of worlds stays in view.
        grid = int(np.ceil(np.sqrt(cfg.num_worlds)))
        zoom = 1.0 + (grid - 1) * cfg.world_spacing / 1.8
        gl.set_camera(wp.vec3(1.2 * zoom, -1.9 * zoom, 1.1 * zoom), -20, 120)
        Path(cfg.video).parent.mkdir(parents=True, exist_ok=True)
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{w}x{h}", "-r", str(cfg.fps), "-i", "-", "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(cfg.video)],
            stdin=subprocess.PIPE,
        )  # fmt: skip
        return gl, ff

    def run(self) -> Path:
        """Simulate headlessly, writing every frame to ``cfg.output``. Returns the path."""
        cfg = self.cfg
        out = Path(cfg.output)
        out.parent.mkdir(parents=True, exist_ok=True)

        # The viewer is only a recorder here: nothing is rendered while simulating.
        viewer = newton.viewer.ViewerViser(verbose=False, record_to_viser=str(out))
        viewer.set_model(self.model)
        viewer.set_world_offsets((cfg.world_spacing, cfg.world_spacing, 0.0))
        try:
            viewer.set_camera(wp.vec3(0.9, -1.4, 0.9), -22, 120)
        except Exception:
            pass

        gl, ff = self._open_video() if cfg.video else (None, None)

        frames = cfg.steps if cfg.steps is not None else self.task_frames
        if cfg.verbose:
            print(
                f"device={self.device} worlds={cfg.num_worlds} bodies={self.model.body_count} "
                f"frames={frames} ({frames * self.frame_dt:.1f}s sim time)"
            )
            active = {k: v for k, v in self.rand_ranges.items() if v > 0}
            if active:
                print("Domain randomization (half-ranges):", active)
            print("Simulating (first frame compiles kernels)...")

        use_graph = cfg.cuda_graph and self.device.is_cuda
        t_wall = time.perf_counter()
        t_steady = t_wall
        first_frame = 0.0
        sim_time = 0.0
        for frame in tqdm(
            range(frames), desc="Simulating", unit="frame", disable=not cfg.verbose
        ):
            if frame == 1:
                wp.synchronize_device(self.device)
                t_steady = time.perf_counter()
                first_frame = t_steady - t_wall
                if cfg.profile:
                    wp.timing_begin(cuda_filter=wp.TIMING_ALL)
            self._update_targets(sim_time)
            self._step_frame()
            if frame == 0 and use_graph:
                # Frame 0 ran eagerly (compiles kernels); later frames replay a graph.
                self._capture_graph()
            viewer.begin_frame(sim_time)
            viewer.log_state(self.state_0)
            viewer.end_frame()
            if gl is not None:
                gl.begin_frame(sim_time)
                gl.log_state(self.state_0)
                gl.end_frame()
                ff.stdin.write(gl.get_frame().numpy().tobytes())
            sim_time += self.frame_dt
        wp.synchronize_device(self.device)
        if cfg.profile and frames > 1:
            wp.timing_print(wp.timing_end())
        wall = time.perf_counter() - t_wall
        steady = time.perf_counter() - t_steady

        err = self.placement_errors()
        if cfg.verbose:
            print(
                f"Done in {wall:.1f}s wall ({frames * cfg.num_worlds / wall:.1f} world-frames/s)"
            )
            if frames > 1:
                n_steady = frames - 1
                print(
                    f"Timing: cuda_graph={'on' if use_graph else 'off'} setup={self.setup_time:.2f}s "
                    f"first_frame={first_frame:.2f}s (kernel compile/cache load) "
                    f"steady={steady:.2f}s = {1e3 * steady / n_steady:.2f} ms/frame "
                    f"({n_steady * cfg.num_worlds / steady:.1f} world-frames/s)"
                )
            print(
                "Cable centroid -> place target error per world [m]:", np.round(err, 3)
            )
        viewer.close()  # also writes the recording
        if gl is not None:
            ff.stdin.close()
            ff.wait()
            gl.close()
            if cfg.verbose:
                print(f"Video written to {cfg.video}")
        return out
