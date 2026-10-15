"""Load workspace source in a fresh interactive Blender, without global installation.

blender --factory-startup --python scripts/dev_addon.py
"""

import sys
from pathlib import Path

if "--factory-startup" not in sys.argv:
    raise RuntimeError("Use a fresh Blender process with --factory-startup")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import blender_agent_marks  # noqa: E402

if Path(blender_agent_marks.__file__).parent != root / "blender_agent_marks":
    raise RuntimeError("Another copy is already loaded; start a fresh Blender process")
blender_agent_marks.register()
print(
    "Loaded workspace FacetCue for Blender. Open N > FacetCue for Blender. No global files changed."
)
