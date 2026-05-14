"""Tests for primitives.audit.policy_loader."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.policy_loader import (  # noqa: E402
    EMPTY_SET_SENTINEL,
    PolicyLoadError,
    PolicySet,
    load_policies,
)


# ---------------------------------------------------------------------------
# Reusable YAML fragments
# ---------------------------------------------------------------------------


BLOCK_YAML = """\
schema_version: "1.0"
policy_id: phi_block_address_in_external_prompt
policy_version: v1.2
match:
  direction: prompt
  destination: external_vendor
  classes:
    any_of:
      - phi:patient_address
verdict: block
block_config:
  user_message: "Patient address detected; blocked."
"""


REDACT_YAML = """\
schema_version: "1.0"
policy_id: phi_redact_dob_in_response
policy_version: v1.0
match:
  direction: response
  destination: any
  classes:
    any_of:
      - phi:patient_dob
verdict: redact
redact_config:
  redact_with: "[REDACTED:{class}]"
"""


def _write(dir_path: Path, name: str, content: str) -> Path:
    p = dir_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class HappyPath(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loads_two_policies(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        _write(self.dir, "redact.yaml", REDACT_YAML)

        ps = load_policies(self.dir)
        self.assertIsInstance(ps, PolicySet)
        self.assertEqual(len(ps.policies), 2)
        self.assertEqual(ps.source_dir, self.dir)
        self.assertFalse(ps.is_empty)
        ids = {p.policy_id for p in ps.policies}
        self.assertEqual(
            ids,
            {"phi_block_address_in_external_prompt", "phi_redact_dob_in_response"},
        )

    def test_by_id_lookup(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        ps = load_policies(self.dir)
        found = ps.by_id("phi_block_address_in_external_prompt")
        self.assertIsNotNone(found)
        self.assertEqual(found.verdict, "block")
        self.assertIsNone(ps.by_id("does_not_exist"))

    def test_yml_extension_also_loaded(self) -> None:
        _write(self.dir, "block.yml", BLOCK_YAML)
        ps = load_policies(self.dir)
        self.assertEqual(len(ps.policies), 1)

    def test_non_yaml_files_ignored(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        _write(self.dir, "README.md", "# notes")
        _write(self.dir, "ignore.txt", "ignore me")
        ps = load_policies(self.dir)
        self.assertEqual(len(ps.policies), 1)

    def test_subdirectory_not_recursed(self) -> None:
        # Single-level glob; nested directory contents are out of scope.
        _write(self.dir, "block.yaml", BLOCK_YAML)
        nested = self.dir / "nested"
        nested.mkdir()
        _write(nested, "redact.yaml", REDACT_YAML)
        ps = load_policies(self.dir)
        self.assertEqual(len(ps.policies), 1)


# ---------------------------------------------------------------------------
# Empty / missing directory
# ---------------------------------------------------------------------------


class EmptyAndMissing(unittest.TestCase):
    def test_empty_dir_returns_empty_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ps = load_policies(Path(tmp))
            self.assertEqual(ps.policy_set_version, EMPTY_SET_SENTINEL)
            self.assertTrue(ps.is_empty)
            self.assertEqual(ps.policies, ())

    def test_missing_dir_raises_filenotfounderror(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_policies(Path("/nonexistent/path/that/does/not/exist"))

    def test_path_is_file_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
            with self.assertRaises(NotADirectoryError):
                load_policies(Path(f.name))


# ---------------------------------------------------------------------------
# Error bundling
# ---------------------------------------------------------------------------


class ErrorBundling(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_yaml_parse_error_raises(self) -> None:
        _write(self.dir, "broken.yaml", "key: : invalid: yaml: ::")
        with self.assertRaises(PolicyLoadError) as ctx:
            load_policies(self.dir)
        self.assertEqual(len(ctx.exception.errors), 1)
        self.assertIn("YAML parse error", ctx.exception.errors[0].message)

    def test_schema_validation_error_raises(self) -> None:
        # Missing required block_config for verdict=block.
        bad = BLOCK_YAML.replace(
            'block_config:\n  user_message: "Patient address detected; blocked."\n',
            "",
        )
        _write(self.dir, "block.yaml", bad)
        with self.assertRaises(PolicyLoadError) as ctx:
            load_policies(self.dir)
        self.assertEqual(len(ctx.exception.errors), 1)
        self.assertIn("schema validation failed", ctx.exception.errors[0].message)

    def test_duplicate_policy_id_rejected(self) -> None:
        _write(self.dir, "first.yaml", BLOCK_YAML)
        _write(self.dir, "second.yaml", BLOCK_YAML)  # same policy_id
        with self.assertRaises(PolicyLoadError) as ctx:
            load_policies(self.dir)
        self.assertEqual(len(ctx.exception.errors), 1)
        self.assertIn("duplicate policy_id", ctx.exception.errors[0].message)

    def test_multiple_errors_bundled(self) -> None:
        # Two bad files — operator sees both at once, not one-fix-per-restart.
        _write(self.dir, "broken1.yaml", "::: bad yaml :::")
        _write(self.dir, "broken2.yaml", "schema_version: 9.9\n")  # bad schema_version
        with self.assertRaises(PolicyLoadError) as ctx:
            load_policies(self.dir)
        self.assertEqual(len(ctx.exception.errors), 2)

    def test_top_level_list_rejected(self) -> None:
        # multi-rule files are out for v0.1.
        _write(self.dir, "list.yaml", "- foo\n- bar\n")
        with self.assertRaises(PolicyLoadError) as ctx:
            load_policies(self.dir)
        self.assertIn(
            "multi-rule files are not supported", ctx.exception.errors[0].message
        )

    def test_one_good_one_bad_still_raises(self) -> None:
        # Spec: any failure means the engine refuses to start.
        _write(self.dir, "good.yaml", BLOCK_YAML)
        _write(self.dir, "bad.yaml", "::: nope :::")
        with self.assertRaises(PolicyLoadError):
            load_policies(self.dir)


# ---------------------------------------------------------------------------
# policy_set_version
# ---------------------------------------------------------------------------


class PolicySetVersion(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_version_is_12_hex_chars(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        ps = load_policies(self.dir)
        self.assertEqual(len(ps.policy_set_version), 12)
        int(ps.policy_set_version, 16)  # is hex

    def test_empty_dir_uses_sentinel(self) -> None:
        ps = load_policies(self.dir)
        self.assertEqual(ps.policy_set_version, EMPTY_SET_SENTINEL)

    def test_version_stable_across_loads(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        _write(self.dir, "redact.yaml", REDACT_YAML)
        ps1 = load_policies(self.dir)
        ps2 = load_policies(self.dir)
        self.assertEqual(ps1.policy_set_version, ps2.policy_set_version)

    def test_version_changes_on_content_change(self) -> None:
        _write(self.dir, "block.yaml", BLOCK_YAML)
        v1 = load_policies(self.dir).policy_set_version

        modified = BLOCK_YAML.replace("v1.2", "v1.3")
        _write(self.dir, "block.yaml", modified)
        v2 = load_policies(self.dir).policy_set_version

        self.assertNotEqual(v1, v2)

    def test_version_changes_on_filename_change(self) -> None:
        # Renaming a file is a real change; version reflects it.
        _write(self.dir, "block.yaml", BLOCK_YAML)
        v1 = load_policies(self.dir).policy_set_version
        (self.dir / "block.yaml").rename(self.dir / "renamed.yaml")
        v2 = load_policies(self.dir).policy_set_version
        self.assertNotEqual(v1, v2)

    def test_version_independent_of_load_order(self) -> None:
        # Two directories with the same files should produce the same version.
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            a, b = Path(tmp_a), Path(tmp_b)
            _write(a, "block.yaml", BLOCK_YAML)
            _write(a, "redact.yaml", REDACT_YAML)
            _write(b, "redact.yaml", REDACT_YAML)
            _write(b, "block.yaml", BLOCK_YAML)
            self.assertEqual(
                load_policies(a).policy_set_version,
                load_policies(b).policy_set_version,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
