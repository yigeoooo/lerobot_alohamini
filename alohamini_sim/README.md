# alohamini_sim

Simulation stack for AlohaMini: turn a phone video of a real room into a photoreal
Isaac Sim scene, generate scripted manipulation episodes in it, and export them as a
[LeRobotDataset](../src/lerobot/datasets/lerobot_dataset.py) that co-trains with real
AlohaMini recordings.

```
alohamini_sim/
├── video2sim/     # phone video → NuRec splat room + TSDF collider in Isaac Sim 5.x
└── data_engine/   # scripted sim episode engine + LeRobotDataset bridge
    ├── engine.py, skills_runtime.py, ...   # episode generation (runs in the sim env)
    ├── writer_adapter.py                   # legacy state-only LeRobot v2.1 writer
    └── lerobot_bridge.py                   # episodes → this repo's LeRobotDataset (v3.0)
```

## Two environments, on purpose

- **`video2sim/` and the engine run in an external GPU toolchain** (Isaac Sim 5.x,
  LingBot-Map, gsplat, ...), **not** in this repo's uv environment. That stack documents
  and validates itself: see [`video2sim/README.md`](video2sim/README.md) and run
  `python -m video2sim.check_env` inside that environment.
- **`data_engine/lerobot_bridge.py` and its tests run in this repo's uv environment.**
  The bridge only needs numpy + the in-repo dataset API, so converted episodes are
  written and validated with the exact same code path real recordings use.

## The bridge

`lerobot_bridge.py` converts engine episodes (per-step 18-D `qpos`, 16-D controller
targets, optional per-camera uint8 RGB) into a v3.0 LeRobotDataset whose feature names
follow the AlohaMini robot convention (`arm_left_*.pos`, `arm_right_*.pos`, `x.vel`,
`y.vel`, `theta.vel`, `lift_axis.height_mm`, `observation.images.<cam>`), so sim data
can be mixed with `lerobot-record` output. See the module docstring for the exact
per-dimension value mapping (base positions → body-frame velocities, lift → mm,
optional gripper 0-100 scaling).

As a library:

```python
from alohamini_sim.data_engine.lerobot_bridge import write_episodes

write_episodes(episodes, repo_id="local/alohamini_sim_pick", root="out/lerobot_ds", fps=20)
```

As a CLI (episodes pickled as a list of engine episode dicts):

```bash
python -m alohamini_sim.data_engine.lerobot_bridge \
    --episodes out/episodes.pkl --repo-id local/alohamini_sim_pick --root out/lerobot_ds
```

## Quickstart: run the bridge tests

```bash
uv sync --locked --extra test --extra dataset   # dataset extra is required by the bridge
uv run pytest tests/test_alohamini_sim_bridge.py -svv
```

The tests build tiny synthetic episodes (10 frames, two 96x96 cameras), write a dataset
into a temp directory, reload it with `LeRobotDataset`, and assert feature names, dtypes,
and joint/pixel/task round-trips — including the `python -m` CLI path.

For the full room pipeline (capture checklist, stage-by-stage commands, GPU/memory
requirements), start at [`video2sim/README.md`](video2sim/README.md).
