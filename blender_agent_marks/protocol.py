"""Shared, dependency-free local connection discovery."""

import hashlib
import os
import tempfile
from pathlib import Path

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def runtime_directory():
    override = os.environ.get("ASM_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    user = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"blender-agent-marks-{user}"
