"""Build a deterministic Blender extension ZIP without publishing."""

import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blender_agent_marks import bl_info


def documentation_sources():
    files = {
        name: ROOT / name
        for name in ("LICENSE", "README.md", "README.zh-CN.md", "CONTRIBUTING.md", "SECURITY.md")
    }
    for directory, suffixes in (
        ("docs", {".md", ".srt"}),
        ("examples", {".toml"}),
        ("contracts", {".json"}),
    ):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                files[path.relative_to(ROOT).as_posix()] = path
    return files


def main():
    version = ".".join(map(str, bl_info["version"]))
    output = ROOT / "dist" / f"facetcue-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    package = ROOT / "blender_agent_marks"
    files = {path.relative_to(package).as_posix(): path for path in package.rglob("*.py")}
    files["blender_manifest.toml"] = ROOT / "blender_agent_marks" / "blender_manifest.toml"
    files.update(documentation_sources())
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            item = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, path.read_bytes())
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Invalid extension archive")
    print(output)


if __name__ == "__main__":
    main()
