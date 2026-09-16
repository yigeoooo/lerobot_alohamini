# ROS2 calibration provenance

The YAML templates, `arm_home.yaml`, and adjacent
`urdf/alohamini2pro_kinematic.urdf` were imported from the local
`alohamini_ros2` project on 2026-09-15:

- `src/alohamini_calibration/config/hardware/`
- `src/alohamini_description/urdf/alohamini2pro_kinematic.urdf`

The templates retain archived robot-specific ticks to document their origin.
They are inputs to `calibration.sync_arm_mapping`, not deployable profiles.
That tool replaces reference ticks, encoder fingerprints and limits from a
fresh capture. `ArmMapping` rejects templates without those fingerprints.

The ROS2 kinematics metadata labels the CAD geometry `cad_export_unverified`
and `calibrated: false`. The base includes +90 degrees of CAD yaw; TCPs are
attached to Fixed_Jaw with the ROS2 tool transform. VR applies current machine
limits at load time rather than using the archived limits in the URDF.

The Python calibration scripts and JointMapper conversions are ported into
`lerobot.vr_gateway.calibration`. ROS package discovery was removed, direct
read-only arm-bus capture was added, and the visualization uses Matplotlib.
No ROS Python modules or external ROS workspace are needed at runtime.
