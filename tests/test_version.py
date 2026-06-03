import unittest
from pathlib import Path
import tomllib

from tools.build_release import package_version
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


if __name__ == "__main__":
    unittest.main()
