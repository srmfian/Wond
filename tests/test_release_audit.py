import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from wond.release_audit import (
    format_release_privacy_audit,
    release_audit_exit_code,
    release_privacy_audit,
)


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git is required")

    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

    def git_add(self, root: Path, *paths: str) -> None:
        subprocess.run(["git", "add", *paths], cwd=root, check=True, capture_output=True)

    def test_tracked_private_file_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_repo(root)
            (root / "config.json").write_text('{"mobile_sync":{"token":"secret-token"}}\n', encoding="utf-8")
            self.git_add(root, "config.json")

            payload = release_privacy_audit(root, include_history=False)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["summary"]["fail"], 1)
        by_id = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(by_id["tracked_private_files"]["status"], "fail")
        self.assertEqual(by_id["tracked_secret_literals"]["status"], "ok")
        self.assertEqual(release_audit_exit_code(payload), 1)

    def test_placeholder_token_is_not_reported_as_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_repo(root)
            (root / ".gitignore").write_text(
                "\n".join(
                    [
                        "config.json",
                        "data/",
                        ".env",
                        ".env.*",
                        ".pcsync/",
                        "*.sqlite",
                        "*.sqlite3",
                        "*.db",
                        ".venv/",
                        "dist/",
                        ".release/",
                        "*.m4a",
                        "*.wav",
                        "*.mp4",
                        "*.mov",
                        "ios/Wond/Config/Signing.local.xcconfig",
                        "*.mobileprovision",
                        "*.p12",
                        "*.pem",
                        "*.key",
                        "ios/Wond/build/",
                        "ios/Wond/DerivedData/",
                        "xcuserdata/",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "config.example.json").write_text(
                '{"mobile_sync":{"token":"change-this-long-random-token"}}\n',
                encoding="utf-8",
            )
            self.git_add(root, ".gitignore", "config.example.json")

            payload = release_privacy_audit(root, include_history=False)

        by_id = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(by_id["tracked_secret_literals"]["status"], "ok")
        self.assertEqual(by_id["tracked_private_files"]["status"], "ok")
        self.assertEqual(release_audit_exit_code(payload), 0)

    def test_secret_literal_is_redacted_in_text_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_repo(root)
            secret = "sk-" + "a" * 32
            (root / "leak.py").write_text(f'OPENAI_API_KEY = "{secret}"\n', encoding="utf-8")
            self.git_add(root, "leak.py")

            payload = release_privacy_audit(root, include_history=False)
            text = format_release_privacy_audit(payload)

        self.assertIn("sk-...[redacted]", text)
        self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
