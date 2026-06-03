import unittest
from pathlib import Path
import tomllib

from tools.build_release import UPDATE_MANAGED_DIRS, UPDATE_MANAGED_FILES, install_command, package_version, update_command
from wond.version import __version__


ROOT = Path(__file__).resolve().parents[1]


def xcconfig_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key} ="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{key} not found in {path}")


class VersionTests(unittest.TestCase):
    def test_python_package_uses_dynamic_version_source(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["dynamic"], ["version"])
        self.assertEqual(pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"], "wond.version.__version__")
        self.assertEqual(package_version(), __version__)

    def test_ios_marketing_version_matches_python_version(self):
        version_config = ROOT / "ios" / "Wond" / "Config" / "Version.xcconfig"
        project_file = ROOT / "ios" / "Wond" / "Wond.xcodeproj" / "project.pbxproj"
        signing_config = ROOT / "ios" / "Wond" / "Config" / "Signing.xcconfig"
        project_text = project_file.read_text(encoding="utf-8")

        self.assertEqual(xcconfig_value(version_config, "WOND_MARKETING_VERSION"), __version__)
        self.assertIn('#include "Version.xcconfig"', signing_config.read_text(encoding="utf-8"))
        self.assertNotIn("MARKETING_VERSION = 0.2;", project_text)
        self.assertIn('MARKETING_VERSION = "$(WOND_MARKETING_VERSION)";', project_text)
        self.assertIn('CURRENT_PROJECT_VERSION = "$(WOND_CURRENT_PROJECT_VERSION)";', project_text)

    def test_update_package_preserves_runtime_state_boundary(self):
        script = update_command("9.9.9")

        self.assertEqual(UPDATE_MANAGED_DIRS, ("wond", "ios", "docs", "tests", "tools"))
        self.assertNotIn("data", UPDATE_MANAGED_DIRS)
        self.assertNotIn(".venv", UPDATE_MANAGED_DIRS)
        self.assertNotIn("config.json", UPDATE_MANAGED_FILES)
        self.assertIn('PAYLOAD_DIR="$PACKAGE_DIR/payload"', script)
        self.assertIn('rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$PAYLOAD_DIR/$dir/" "$INSTALL_DIR/$dir/"', script)
        self.assertNotIn('rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$PAYLOAD_DIR/" "$INSTALL_DIR/"', script)
        self.assertIn('Protected local files were not replaced: config.json, data/', script)
        self.assertIn('install-dashboard-agent --load', script)

    def test_installer_uses_system_applications_with_legacy_fallback(self):
        script = install_command("9.9.9")

        self.assertIn('SYSTEM_INSTALL_DIR="/Applications/Wond"', script)
        self.assertIn('LEGACY_INSTALL_DIR="$HOME/Applications/Wond"', script)
        self.assertIn('[ -d "$LEGACY_INSTALL_DIR/wond" ] && [ ! -d "$SYSTEM_INSTALL_DIR/wond" ]', script)
        self.assertIn('Unable to write $SYSTEM_INSTALL_DIR; falling back to $LEGACY_INSTALL_DIR.', script)
        self.assertIn('ln -s "$INSTALL_REAL" "$SYSTEM_INSTALL_DIR"', script)

    def test_updater_finds_system_or_legacy_install(self):
        script = update_command("9.9.9")

        self.assertIn('SYSTEM_INSTALL_DIR="/Applications/Wond"', script)
        self.assertIn('LEGACY_INSTALL_DIR="$HOME/Applications/Wond"', script)
        self.assertIn('[ -d "$SYSTEM_INSTALL_DIR/wond" ]', script)
        self.assertIn('[ -d "$LEGACY_INSTALL_DIR/wond" ]', script)
        self.assertIn('Checked default locations: $SYSTEM_INSTALL_DIR and $LEGACY_INSTALL_DIR.', script)


if __name__ == "__main__":
    unittest.main()
