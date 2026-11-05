import logging
import os
import uuid
import pytest
from unittest.mock import patch, MagicMock

import agent
from agent import compute_offline_uuid, handle_accounts_auth_offline
from nlc.net.capes import upload_mojang_skin
from nlc.core.vault import VaultManager, decrypt as vault_decrypt
from nlc.net.elyby_auth import ElyByAuth
from nlc.net.ms_auth import MicrosoftDeviceAuth


def test_compute_offline_uuid_known_vectors():
    """Verify compute_offline_uuid matches authentic Minecraft / Java UUID.nameUUIDFromBytes vectors."""
    vectors = {
        "Steve": "5627dd98-e6be-3c21-b8a8-e92344183641",
        "Alex": "36532b5e-c442-3dbb-a24c-c7e55d0f979a",
        "Notch": "b50ad385-829d-3141-a216-7e7d7539ba7f",
        "Player_123": "592ac8aa-a392-3300-916e-00427a650c3b",
    }
    for username, expected in vectors.items():
        res = compute_offline_uuid(username)
        assert res == expected, f"UUID for {username} did not match expected authentic vector: {res} != {expected}"

        u = uuid.UUID(res)
        assert u.version == 3
        assert u.variant == uuid.RFC_4122


def test_compute_offline_uuid_unicode():
    """Verify Unicode usernames are properly encoded to UTF-8 without crashing or producing wrong variant."""
    unicode_names = ["Игрок", "テスト", "Spöke", "🎮Player"]
    for name in unicode_names:
        res = compute_offline_uuid(name)
        u = uuid.UUID(res)
        assert u.version == 3
        assert u.variant == uuid.RFC_4122


def test_handle_accounts_auth_offline_matches_compute_offline_uuid(tmp_path, monkeypatch):
    """Verify handle_accounts_auth_offline creates accounts with identical UUIDs to compute_offline_uuid."""
    config_file = tmp_path / "launcher_config.json"
    config_file.write_text('{"profiles": [], "accounts": []}', encoding="utf-8")
    monkeypatch.setattr("agent.get_config_dir", lambda: str(tmp_path))

    res = handle_accounts_auth_offline({"username": "TestPlayer", "skin_model": "classic"})
    assert res["status"] == "success"
    profile = res["profile"]
    expected_uuid = compute_offline_uuid("TestPlayer")
    assert profile["uuid"] == expected_uuid


def test_upload_mojang_skin_does_not_log_tokens(caplog):
    """Ensure upload_mojang_skin never logs cleartext or boolean tokens to logger."""
    sensitive_token = "secret_mc_bearer_token_xyz_9999"
    with caplog.at_level(logging.WARNING, logger="nlc.net.capes"):
        res = upload_mojang_skin(sensitive_token, "non_existent_skin_file.png")
        assert res is False

    for record in caplog.records:
        assert sensitive_token not in record.message
        assert "token=" not in record.message
        assert "access_token" not in record.message


def test_vault_decrypt_unknown_prefix_does_not_log_ciphertext(caplog):
    """Ensure vault_decrypt does not slice or leak raw unencrypted payload into logs."""
    sensitive_plaintext = "vault:custom_unsupported_secret_token_1234567890"
    vm = VaultManager()
    with caplog.at_level(logging.WARNING, logger="nlc.core.vault"):
        res = vm.decrypt(sensitive_plaintext)
        assert res == ""

    for record in caplog.records:
        assert sensitive_plaintext not in record.message
        assert "custom_unsupported_secret" not in record.message
        assert "ciphertext (length=" in record.message


def test_elyby_auth_exception_does_not_leak_password(caplog):
    """Ensure network errors during ElyBy authentication do not leak passwords in logs."""
    secret_pw = "UltraSecretPassword123!"
    with patch("nlc.net.elyby_auth.get_http_session") as mock_sess:
        mock_sess.return_value.post.side_effect = RuntimeError(f"Connection refused with payload secret: {secret_pw}")
        with caplog.at_level(logging.ERROR, logger="nlc.net.elyby_auth"):
            res = ElyByAuth.authenticate("Steve", secret_pw)
            assert "error" in res

    for record in caplog.records:
        assert secret_pw not in record.message
        assert "RuntimeError" in record.message


def test_ms_auth_poll_token_transient_error_sanitization(caplog):
    """Ensure polling errors do not leak device codes or auth details into logs."""
    secret_device_code = "device_code_secret_abc123"
    auth = MicrosoftDeviceAuth(client_id="dummy-client-id")
    with patch("nlc.net.ms_auth.get_http_session") as mock_sess:
        mock_sess.return_value.post.side_effect = Exception(f"Failed HTTP call with code {secret_device_code}")
        with caplog.at_level(logging.WARNING, logger="nlc.net.ms_auth"):
            # Run 1 polling attempt
            res = auth.poll_token(secret_device_code, interval=0.01, expires_in=0.02)
            assert "error" in res

    for record in caplog.records:
        assert secret_device_code not in record.message
        assert "Exception" in record.message
