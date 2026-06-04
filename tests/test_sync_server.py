import base64
import hashlib
import hmac
import io
import tempfile
import time
import unittest
import zipfile
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from wond.sync_server import (
    cleanup_upload_artifacts,
    extract_zip_safely,
    save_upload_stream,
    upload_auth_preflight,
    verify_api_auth,
    verify_upload_auth,
)


def sync_settings(root: Path, token: str = "sync-secret", **mobile_sync):
    config = {
        "token": token,
        "require_encrypted_uploads": True,
    }
    config.update(mobile_sync)
    return SimpleNamespace(data_dir=root / "data", mobile_sync=config)


def signed_upload_headers(token: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    sent_at = str(timestamp if timestamp is not None else int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{sent_at}\n{body_hash}".encode("utf-8")
    signature = base64.b64encode(hmac.new(token.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
    return {
        "X-Wond-Timestamp": sent_at,
        "X-Wond-Body-SHA256": body_hash,
        "X-Wond-Signature": signature,
    }


def signed_api_headers(token: str, method: str, target: str, body: bytes) -> dict[str, str]:
    sent_at = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{sent_at}\n{method.upper()}\n{target}\n{body_hash}".encode("utf-8")
    signature = base64.b64encode(hmac.new(token.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
    return {
        "X-Wond-Timestamp": sent_at,
        "X-Wond-Body-SHA256": body_hash,
        "X-Wond-Signature": signature,
    }


class SyncServerSecurityTests(unittest.TestCase):
    def test_upload_rejects_missing_server_token_before_body_is_saved(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp), token="")
            headers = signed_upload_headers("client-token", b"body")

            result = upload_auth_preflight(settings, headers, encrypted=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, HTTPStatus.SERVICE_UNAVAILABLE)
            self.assertEqual(result.error, "sync_token_required")

    def test_upload_rejects_missing_auth_headers(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp))

            result = upload_auth_preflight(settings, {}, encrypted=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, HTTPStatus.UNAUTHORIZED)

    def test_upload_requires_encrypted_envelope_by_default(self):
        body = b"plain zip bytes"
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp))
            upload_path = save_upload_stream(settings, io.BytesIO(body), len(body), "upload.zip", encrypted=False)

            result = verify_upload_auth(settings, upload_path, signed_upload_headers("sync-secret", body), encrypted=False)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, HTTPStatus.BAD_REQUEST)
            self.assertEqual(result.error, "encrypted_upload_required")

    def test_valid_encrypted_upload_auth_is_accepted(self):
        body = b'{"version":1,"algorithm":"AES-256-GCM"}'
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp))
            upload_path = save_upload_stream(settings, io.BytesIO(body), len(body), "upload.pcsync", encrypted=True)

            result = verify_upload_auth(settings, upload_path, signed_upload_headers("sync-secret", body), encrypted=True)

            self.assertTrue(result.ok)

    def test_rejected_upload_artifact_is_removed_from_inbox(self):
        body = b"encrypted payload"
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp))
            upload_path = save_upload_stream(settings, io.BytesIO(body), len(body), "upload.pcsync", encrypted=True)
            bad_headers = signed_upload_headers("sync-secret", b"different body")

            result = verify_upload_auth(settings, upload_path, bad_headers, encrypted=True)
            if not result.ok:
                cleanup_upload_artifacts(settings, upload_path)

            self.assertFalse(result.ok)
            self.assertFalse(upload_path.exists())

    def test_incomplete_upload_stream_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            settings = sync_settings(root)

            with self.assertRaisesRegex(ValueError, "Content-Length"):
                save_upload_stream(settings, io.BytesIO(b"short"), 99, "partial.pcsync", encrypted=True)

            inbox = root / "data" / "mobile_sync" / "inbox"
            self.assertEqual(list(inbox.glob("*")), [])

    def test_api_auth_rejects_invalid_body_hash_shape(self):
        body = b"{}"
        headers = signed_api_headers("sync-secret", "POST", "/ask", body)
        headers["X-Wond-Body-SHA256"] = "not-a-sha"
        with tempfile.TemporaryDirectory() as raw_tmp:
            settings = sync_settings(Path(raw_tmp))

            self.assertFalse(verify_api_auth(settings, headers, "POST", "/ask", body))

    def test_zip_extract_rejects_sibling_directory_escape(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            zip_path = root / "evil.zip"
            destination = root / "safe"
            destination.mkdir()
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("safe-first.txt", "ok")
                archive.writestr("../safe-evil/pwned.txt", "bad")

            with self.assertRaisesRegex(ValueError, "unsafe zip path"):
                extract_zip_safely(zip_path, destination)

            self.assertFalse((destination / "safe-first.txt").exists())
            self.assertFalse((root / "safe-evil" / "pwned.txt").exists())


if __name__ == "__main__":
    unittest.main()
