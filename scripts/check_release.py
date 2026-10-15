"""Verify current release archives and install the extension in an isolated Blender."""

import argparse
import hashlib
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile
from email.parser import Parser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blender_agent_marks import bl_info
from scripts.package_addon import documentation_sources

INSTALL_SCRIPT = """
import addon_utils, bpy, importlib, json, sys, tomllib
from pathlib import Path
args = sys.argv[sys.argv.index('--') + 1:]
package, work = Path(args[0]), Path(args[1])
bpy.context.preferences.extensions.repos.new(name='Release check', module='asm_release_test', custom_directory=str(work / 'repo'))
result = bpy.ops.extensions.package_install_files('EXEC_DEFAULT', repo='asm_release_test', filepath=str(package), enable_on_install=True)
assert result == {'FINISHED'}, result
addon = importlib.import_module('bl_ext.asm_release_test.blender_agent_marks')
assert Path(addon.__file__).is_relative_to(work), addon.__file__
addon_info = addon_utils.module_bl_info(addon)
assert addon_info['name'] == 'FacetCue for Blender'
assert addon.ui.ASM_PT_panel.bl_category == 'FacetCue for Blender'
assert addon.connection._server is not None, addon.connection.LAST_ERROR
obj = bpy.data.objects['Cube']
obj.data.calc_loop_triangles()
from mathutils import Vector
tri = obj.data.loop_triangles[0]
point = sum((obj.data.vertices[i].co for i in tri.vertices), Vector()) / 3
record = addon.api.create(bpy.context.scene, obj.name, 0, point, 'Installed extension test')
data = addon.api.get_surface_annotations(include_visibility=False)
assert data['annotations'][0]['id'] == record['id']
descriptor = addon.connection._server.path
assert descriptor.exists()
bpy.ops.preferences.addon_disable(module=addon.__name__)
assert not descriptor.exists()
manifest = tomllib.loads((Path(addon.__file__).parent / 'blender_manifest.toml').read_text())
assert manifest['name'] == addon_info['name']
version = manifest['version']
(work / 'installed.json').write_text(json.dumps({'version': version, 'blender': bpy.app.version_string, 'module': addon.__name__}), encoding='utf-8')
"""


def inspect_files(names):
    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate archive entries")
    forbidden = {
        "artifacts",
        ".venv",
        ".git",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
        "__MACOSX",
        "adapters",
        "build",
        "dist",
    }
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ":" in name
            or forbidden.intersection(path.parts)
        ):
            raise RuntimeError(f"Unexpected archive entry: {name}")
        if path.suffix.lower() in {".pyc", ".blend", ".blend1", ".log", ".tmp", ".exe", ".dll"}:
            raise RuntimeError(f"Unexpected binary or local artifact: {name}")


def package_sources():
    sources = {
        source.relative_to(ROOT).as_posix(): source
        for package in ("blender_agent_marks", "agent_mcp")
        for source in (ROOT / package).rglob("*.py")
    }
    manifest = "blender_agent_marks/blender_manifest.toml"
    sources[manifest] = ROOT / manifest
    return sources


def project_sources():
    sources = package_sources()
    for name in (
        "LICENSE",
        "README.md",
        "README.zh-CN.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "AGENTS.md",
        "MANIFEST.in",
        "pyproject.toml",
        "ruff.toml",
        "requirements-dev.txt",
        ".gitignore",
        ".gitattributes",
    ):
        sources[name] = ROOT / name
    for directory, suffixes in (
        ("scripts", {".py"}),
        ("tests", {".py"}),
        ("docs", {".md", ".srt"}),
        ("contracts", {".json"}),
        ("examples", {".toml"}),
        (".github", {".yml", ".md"}),
    ):
        for source in (ROOT / directory).rglob("*"):
            if source.is_file() and source.suffix in suffixes:
                sources[source.relative_to(ROOT).as_posix()] = source
    return sources


def verify_sources(names, read, sources, *, exact=False, generated=()):
    names = set(names)
    unexpected = names - sources.keys() - set(generated)
    if exact and unexpected:
        raise RuntimeError(f"Unexpected archive entry: {sorted(unexpected)}")
    code_entries = {
        name
        for name in names
        if name.endswith(".py") or PurePosixPath(name).name == "blender_manifest.toml"
    }
    unexpected = code_entries - sources.keys()
    if unexpected:
        raise RuntimeError(f"Unexpected archive source: {sorted(unexpected)}")
    for entry, source in sources.items():
        if entry not in names:
            raise RuntimeError(f"Archive source is missing: {entry}")
        if read(entry) != source.read_bytes():
            raise RuntimeError(f"Archive source is stale: {entry}")


def verify_metadata(raw, version):
    metadata = Parser().parsestr(raw.decode("utf-8"))
    for field, expected in (
        ("Name", "facetcue"),
        ("Version", version),
        ("License-Expression", "GPL-3.0-or-later"),
    ):
        if metadata[field] != expected:
            raise RuntimeError(f"Package metadata mismatch: {field}")


def verify_documentation(names, read):
    names = set(names)
    for name in sorted(names):
        if not name.endswith(".md"):
            continue
        text = read(name).decode("utf-8")
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
            target = urlsplit(target.strip("<>"))
            if target.scheme or target.netloc or not target.path:
                continue
            resolved = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), unquote(target.path))
            )
            if resolved not in names:
                raise RuntimeError(f"Broken documentation link: {name} -> {target.path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default=os.environ.get("BLENDER_BIN"))
    options = parser.parse_args()
    version = ".".join(map(str, bl_info["version"]))
    for name in ("pyproject.toml", "blender_agent_marks/blender_manifest.toml"):
        match = re.search(r'^version = "([^"]+)"', (ROOT / name).read_text(), re.MULTILINE)
        if not match or match[1] != version:
            raise RuntimeError(f"Version mismatch: {name}")
    paths = [
        ROOT / "dist" / name
        for name in (
            f"facetcue-{version}.zip",
            f"facetcue-{version}-py3-none-any.whl",
            f"facetcue-{version}.tar.gz",
        )
    ]
    sources = package_sources()
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"Missing release artifact: {path.name}")
        if path.suffix == ".gz":
            with tarfile.open(path) as archive:
                inspect_files(archive.getnames())
                if any(not (item.isfile() or item.isdir()) for item in archive.getmembers()):
                    raise RuntimeError("Source archive contains a link or special file")
                prefix = f"facetcue-{version}/"
                generated = [prefix + name for name in ("PKG-INFO", "setup.cfg")]
                generated += [
                    prefix + "facetcue.egg-info/" + name
                    for name in (
                        "PKG-INFO",
                        "SOURCES.txt",
                        "dependency_links.txt",
                        "entry_points.txt",
                        "requires.txt",
                        "top_level.txt",
                    )
                ]
                verify_sources(
                    [item.name for item in archive.getmembers() if item.isfile()],
                    lambda name: archive.extractfile(name).read(),
                    {prefix + name: source for name, source in project_sources().items()},
                    exact=True,
                    generated=generated,
                )
                verify_metadata(archive.extractfile(prefix + "PKG-INFO").read(), version)
                verify_documentation(
                    [item.name for item in archive.getmembers() if item.isfile()],
                    lambda name: archive.extractfile(name).read(),
                )
        else:
            with ZipFile(path) as archive:
                inspect_files(archive.namelist())
                if archive.testzip():
                    raise RuntimeError(f"Corrupt archive: {path.name}")
                generated = []
                if path.suffix == ".zip":
                    expected = {
                        name.removeprefix("blender_agent_marks/"): source
                        for name, source in sources.items()
                        if name.startswith("blender_agent_marks/")
                    }
                    expected.update(documentation_sources())
                else:
                    metadata_root = f"facetcue-{version}.dist-info/"
                    expected = {**sources, metadata_root + "licenses/LICENSE": ROOT / "LICENSE"}
                    generated = [
                        metadata_root + name
                        for name in (
                            "METADATA",
                            "WHEEL",
                            "entry_points.txt",
                            "top_level.txt",
                            "RECORD",
                        )
                    ]
                    verify_metadata(archive.read(metadata_root + "METADATA"), version)
                verify_sources(
                    archive.namelist(), archive.read, expected, exact=True, generated=generated
                )
                verify_documentation(archive.namelist(), archive.read)
    with tempfile.TemporaryDirectory(prefix="asm_wheel_") as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", tmp, str(paths[1])],
            check=True,
            capture_output=True,
        )
        code = (
            "import sys, asyncio; from pathlib import Path; "
            "from importlib.metadata import distribution; "
            f"sys.path.insert(0, {tmp!r}); "
            "from agent_mcp import server; "
            f"assert Path(server.__file__).is_relative_to({tmp!r}); "
            "entry = next(e for e in distribution('facetcue').entry_points "
            "if e.group == 'console_scripts' and e.name == 'facetcue'); "
            "assert entry.load() is server.main; "
            "names={tool.name for tool in asyncio.run(server.build_server().list_tools())}; "
            "assert names == {'get_surface_annotations','submit_annotation_changes'}; "
            "print('Installed wheel tool discovery passed')"
        )
        subprocess.run([sys.executable, "-I", "-c", code], check=True)
    if options.blender:
        with tempfile.TemporaryDirectory(prefix="asm_release_") as tmp:
            work = Path(tmp)
            env = dict(
                os.environ,
                BLENDER_USER_CONFIG=tmp,
                BLENDER_USER_EXTENSIONS=str(work / "extensions"),
                ASM_RUNTIME_DIR=str(work / "connection"),
                TMP=tmp,
                TEMP=tmp,
                TMPDIR=tmp,
            )
            script = work / "install.py"
            script.write_text(INSTALL_SCRIPT, encoding="utf-8")
            common = [options.blender, "--background", "--factory-startup", "--threads", "2"]
            for command in (
                common + ["--command", "extension", "validate", str(paths[0])],
                common
                + ["--python-exit-code", "1", "--python", str(script), "--", str(paths[0]), tmp],
            ):
                result = subprocess.run(
                    command, env=env, text=True, capture_output=True, timeout=120
                )
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
            print("Installed extension:", (work / "installed.json").read_text())
    else:
        print("Archive checks passed; supply --blender for install verification.")
    (ROOT / "dist" / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in paths
        ),
        encoding="utf-8",
    )
    print("Release archives verified. Nothing was published.")


if __name__ == "__main__":
    main()
