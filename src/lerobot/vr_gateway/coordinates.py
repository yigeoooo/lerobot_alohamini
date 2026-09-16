"""WebXR metres and XYZW orientations mapped into standard robot base axes."""

import numpy as np

# +X right, +Y up, -Z forward -> +X forward, +Y left, +Z up.
XR_TO_BASE = np.array([[0.0, 0.0, -1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


def aligned_xr_basis(head_rotation: np.ndarray) -> np.ndarray:
    """Latch horizontal viewing direction; ignore head pitch and roll."""
    forward = head_rotation @ np.array([0.0, 0.0, -1.0])
    forward[1] = 0.0
    norm = np.linalg.norm(forward)
    if norm < 1e-6:
        raise ValueError("Look horizontally before aligning")
    forward /= norm
    up = np.array([0.0, 1.0, 0.0])
    heading = np.column_stack((np.cross(forward, up), up, -forward))
    return XR_TO_BASE @ heading.T
