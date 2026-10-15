"""Run isolated checks. No packaging, user configuration changes, or live Blender edits.

Default: Python unit tests. Add --blender PATH for background data checks,
--gui for viewport/input regressions, --mcp for a real MCP stdio round trip.
Install the project with its dev extra before running MCP checks.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts"
BLENDER_CHECKS = [
    ("blender_smoke.py", "blender_test_report.json", None),
    ("blender_data_regression.py", "data_regression_report.json", None),
    ("blender_reload_smoke.py", "reload_test_report.json", None),
    ("blender_spatial_regression.py", "spatial_test_report.json", None),
]
GUI_CHECKS = [
    ("blender_popup_position_smoke.py", "drag_test_report.json", "drag_test_error.txt"),
    ("blender_dialog_smoke.py", "dialog_test_report.json", "dialog_test_error.txt"),
    ("blender_delete_smoke.py", "delete_test_report.json", "delete_test_error.txt"),
    ("blender_floating_smoke.py", "floating_test_report.json", "floating_test_error.txt"),
    ("blender_gui_smoke.py", "gui_test_report.json", "gui_test_error.txt"),
    ("blender_orbit_regression.py", "orbit_test_report.json", "orbit_test_error.txt"),
    ("blender_mixed_scene_smoke.py", "mixed_scene_report.json", "mixed_scene_error.txt"),
    (
        "blender_visibility_cache_regression.py",
        "visibility_cache_report.json",
        "visibility_cache_error.txt",
    ),
    ("blender_ux_smoke.py", "ux_test_report.json", "ux_test_error.txt"),
    ("blender_review_smoke.py", "review_test_report.json", "review_test_error.txt"),
]


def run(command, name, env=None):
    """subprocess.run kills only its own child on timeout; stale reports cannot pass."""
    print(f"Running {name}", flush=True)
    with (OUT / f"check_{name}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    if result.returncode:
        raise RuntimeError(f"{name} exited {result.returncode}; see artifacts/check_{name}.log")


def require_report(filename, error_file=None):
    path = OUT / filename
    if error_file and (OUT / error_file).exists():
        raise RuntimeError((OUT / error_file).read_text(encoding="utf-8"))
    if not path.is_file():
        raise RuntimeError(f"Missing fresh test report: {filename}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not report.get("checks") or report.get("checks_passed") != len(report["checks"]):
        raise RuntimeError(f"Invalid test report: {filename}")
    print(f"Passed {filename}: {report['checks_passed']} checks", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default=os.environ.get("BLENDER_BIN"))
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--mcp", action="store_true")
    options = parser.parse_args()
    if (options.gui or options.mcp) and not options.blender:
        options.blender = shutil.which("blender")
        if not options.blender:
            parser.error("Provide --blender or BLENDER_BIN for Blender checks")
    OUT.mkdir(exist_ok=True)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], "unit")
    if options.blender:
        cases = BLENDER_CHECKS + (GUI_CHECKS if options.gui else [])
        for script, report, error in cases:
            (OUT / report).unlink(missing_ok=True)
            if error:
                (OUT / error).unlink(missing_ok=True)
            command = [
                options.blender,
                "--factory-startup",
                "--threads",
                "2",
                "--python-exit-code",
                "1",
            ]
            if (script, report, error) in GUI_CHECKS:
                command += [
                    "--enable-event-simulate",
                    "--no-window-focus",
                    "--window-geometry",
                    "0",
                    "0",
                    "1440",
                    "1000",
                ]
            else:
                command += ["--background"]
            command += ["--python", str(ROOT / "tests" / script)]
            # Blender writes quit.blend even in a test GUI. Keep it away from the
            # user's recovery file as well as isolating normal temp files.
            with tempfile.TemporaryDirectory(prefix="asm_check_", dir=OUT) as tmp:
                run(
                    command,
                    Path(script).stem,
                    dict(
                        os.environ,
                        TMP=tmp,
                        TEMP=tmp,
                        TMPDIR=tmp,
                        BLENDER_USER_CONFIG=tmp,
                        ASM_RUNTIME_DIR=str(Path(tmp) / "connection"),
                    ),
                )
            require_report(report, error)
    if options.mcp:
        report = "mcp_read_test_report.json"
        (OUT / report).unlink(missing_ok=True)
        command = [sys.executable, "tests/mcp_integration.py", "--blender", options.blender]
        run(command, "mcp")
        require_report(report)
    print("All requested checks passed. No package was built.")


if __name__ == "__main__":
    main()
