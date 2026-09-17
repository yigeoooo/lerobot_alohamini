"""Archived paired calibration for offline IK checks; never a live robot profile."""

import json
from pathlib import Path

import pytest
import yaml

from lerobot.vr_gateway.calibration.profile import ASSET_DIR, ArmMapping
from lerobot.vr_gateway.calibration.sync_arm_mapping import build_side_mapping


@pytest.fixture
def mapping():
    calibration = json.loads((Path(__file__).parent / "fixtures/ros2_reference_calibration.json").read_text())
    templates = {
        side: yaml.safe_load((ASSET_DIR / f"calibration/hardware_joint_map_{side}.yaml").read_text())
        for side in ("left", "right")
    }
    ticks = {
        f"arm_{side}_{name}": entry["reference_tick"]
        for side in templates
        for name, entry in templates[side]["joints"].items()
    }
    profiles = {
        side: build_side_mapping(
            templates[side], calibration, ticks, side, {"captured_at": "offline fixture", "host": "offline"}
        )
        for side in templates
    }
    return ArmMapping(profiles, calibration)


@pytest.fixture
def mapping_dir(mapping, tmp_path):
    directory = tmp_path / "arm_mapping"
    directory.mkdir()
    (directory / "AlohaMiniRobot.json").write_text(json.dumps(mapping.calibration))
    for side, profile in mapping.mappings.items():
        (directory / f"hardware_joint_map_{side}.yaml").write_text(yaml.safe_dump(profile))
    return directory


@pytest.fixture
def legacy_ik_factory(mapping, mapping_dir):
    pytest.importorskip("placo")
    from lerobot.vr_gateway.server import make_vr_arm_ik

    def make(**options):
        return make_vr_arm_ik(mapping.calibration, mode="legacy", mapping_dir=mapping_dir, **options)

    return make
