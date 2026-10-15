"""Reject missing, extra or stale code in release archives."""

import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.check_release import (
    inspect_files,
    project_sources,
    verify_documentation,
    verify_metadata,
    verify_sources,
)
from scripts.package_addon import documentation_sources


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.sources = {}
        for name in (
            "blender_agent_marks/connection.py",
            "agent_mcp/bridge.py",
            "blender_agent_marks/blender_manifest.toml",
        ):
            source = root / name
            source.parent.mkdir(exist_ok=True)
            source.write_bytes(b"current source\n")
            self.sources[name] = source
        self.entries = {name: source.read_bytes() for name, source in self.sources.items()}

    def verify(self, entries, *, exact=False):
        data = io.BytesIO()
        with ZipFile(data, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        with ZipFile(data) as archive:
            verify_sources(archive.namelist(), archive.read, self.sources, exact=exact)

    def test_matching_sources(self):
        self.verify(self.entries)

    def test_stale_sources_and_manifest(self):
        for name in self.entries:
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "stale"):
                self.verify({**self.entries, name: b"previous source\n"})

    def test_missing_sources_and_manifest(self):
        for name in self.entries:
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "missing"):
                self.verify({key: value for key, value in self.entries.items() if key != name})

    def test_obsolete_code_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Unexpected archive source"):
            self.verify({**self.entries, "agent_mcp/obsolete.py": b"obsolete source\n"})

    def test_exact_archives_reject_diagnostic_files(self):
        self.verify(self.entries, exact=True)
        for name in ("probe.json", "previous-copy.txt", "__MACOSX/._connection.py"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "Unexpected"):
                self.verify({**self.entries, name: b"temporary"}, exact=True)

    def test_only_known_generated_metadata_allowed(self):
        generated = "package.dist-info/METADATA"
        entries = {**self.entries, generated: b"generated"}
        verify_sources(
            entries, entries.__getitem__, self.sources, exact=True, generated=[generated]
        )
        for name in ("package.dist-info/diagnostic.json", "agent_mcp/runtime.json"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "Unexpected"):
                verify_sources(
                    {**entries, name: b"temporary"},
                    entries.__getitem__,
                    self.sources,
                    exact=True,
                    generated=[generated],
                )

    def test_project_inventory_includes_developer_files(self):
        sources = project_sources()
        for name in (
            "MANIFEST.in",
            "README.zh-CN.md",
            "scripts/check_release.py",
            "tests/test_release.py",
            "contracts/live_mcp_tools.json",
            "examples/codex-mcp.example.toml",
            "docs/release-notes.md",
            "docs/video-main.zh-CN.srt",
            "docs/video-vertical.zh-CN.srt",
            ".github/pull_request_template.md",
            ".github/workflows/checks.yml",
        ):
            with self.subTest(name=name):
                self.assertIn(name, sources)
        self.assertTrue(all(path.is_file() for path in sources.values()))

    def test_extension_documentation_is_complete(self):
        sources = documentation_sources()
        self.assertIn("LICENSE", sources)
        self.assertIn("docs/guide.zh-CN.md", sources)
        self.assertIn("examples/codex-mcp.example.toml", sources)
        verify_documentation(sources, lambda name: sources[name].read_bytes())

    def test_documentation_rejects_missing_local_targets(self):
        entries = {
            "README.md": b"[Guide](docs/guide.md#install) [Web](https://example.org) [Top](#top)",
            "docs/guide.md": b"[License](../LICENSE) [API](<api%20reference.md>)",
            "docs/api reference.md": b"API",
            "LICENSE": b"License",
        }
        verify_documentation(entries, entries.__getitem__)
        for name in ("LICENSE", "docs/api reference.md"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "Broken"):
                verify_documentation(entries.keys() - {name}, entries.__getitem__)

    def test_archive_rejects_cache_paths_and_duplicates(self):
        for names in (
            ["ok.py", "ok.py"],
            ["../secret"],
            ["C:/secret"],
            ["..\\secret"],
            ["package/.ruff_cache/data"],
            ["package/__pycache__/module.pyc"],
            ["package/scene.blend1"],
            ["package/session.log"],
        ):
            with self.subTest(names=names), self.assertRaises(RuntimeError):
                inspect_files(names)

    def test_metadata_version_and_license(self):
        raw = b"Name: facetcue\nVersion: 1.2.3\nLicense-Expression: GPL-3.0-or-later\n"
        verify_metadata(raw, "1.2.3")
        for changed in (raw.replace(b"1.2.3", b"1.2.2"), raw.replace(b"GPL-3.0-or-later", b"MIT")):
            with (
                self.subTest(raw=changed),
                self.assertRaisesRegex(RuntimeError, "metadata mismatch"),
            ):
                verify_metadata(changed, "1.2.3")


if __name__ == "__main__":
    unittest.main()
