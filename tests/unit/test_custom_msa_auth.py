import os
import pytest
from unittest.mock import patch, MagicMock
from nlc.net.ms_auth import (
    DEFAULT_MSA_CLIENT_ID,
    PRISM_FALLBACK_CLIENT_ID,
    get_msa_client_id,
    get_msa_redirect_uri,
    MicrosoftDeviceAuth,
)
from agent import get_config_manager, handle_accounts_auth_microsoft_start


def test_default_msa_client_id_is_user_app():
    assert DEFAULT_MSA_CLIENT_ID == "9d6a0dfb-42b0-46a4-a904-1d4557409da7"
    assert PRISM_FALLBACK_CLIENT_ID == "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"


def test_get_msa_client_id_resolution(monkeypatch, tmp_path):
    # Case 1: Environment variable takes highest priority
    monkeypatch.setenv("NLC_MSA_CLIENT_ID", "custom-env-client-id-1234")
    assert get_msa_client_id() == "custom-env-client-id-1234"

    monkeypatch.delenv("NLC_MSA_CLIENT_ID", raising=False)

    cm = get_config_manager()
    original_cfg = cm.load()
    try:
        # Case 2: Config provider setting 'Default(NLC)'
        cfg = cm.load()
        cfg["msa_auth_provider"] = "Default(NLC)"
        cfg["msa_client_id"] = "ignored-id"
        cm.save(cfg)
        assert get_msa_client_id() == DEFAULT_MSA_CLIENT_ID

        # Case 3: Config provider setting 'Prism'
        cfg["msa_auth_provider"] = "Prism"
        cm.save(cfg)
        assert get_msa_client_id() == PRISM_FALLBACK_CLIENT_ID

        # Case 4: Config provider setting 'Custom' with valid ID
        cfg["msa_auth_provider"] = "Custom"
        cfg["msa_client_id"] = "custom-user-azure-guid"
        cm.save(cfg)
        assert get_msa_client_id() == "custom-user-azure-guid"

        # Case 5: Direct config msa_client_id without provider
        cfg.pop("msa_auth_provider", None)
        cfg["msa_client_id"] = "config-specified-client-id-5678"
        cm.save(cfg)
        assert get_msa_client_id() == "config-specified-client-id-5678"

        # Case 6: Empty string falls back to default
        cfg["msa_client_id"] = "   "
        cm.save(cfg)
        assert get_msa_client_id() == DEFAULT_MSA_CLIENT_ID

        # Case 7: Absent key falls back to default
        cfg.pop("msa_client_id", None)
        cm.save(cfg)
        assert get_msa_client_id() == DEFAULT_MSA_CLIENT_ID
    finally:
        cm.save(original_cfg)


def test_redirect_uri_matches_client():
    uri = get_msa_redirect_uri()
    assert "ms-auth.minecraftservices.com" in uri or "nativeclient" in uri


def test_microsoft_device_auth_initializes_with_resolved_client_id(monkeypatch):
    monkeypatch.setenv("NLC_MSA_CLIENT_ID", "test-device-auth-id")
    auth = MicrosoftDeviceAuth()
    assert auth.client_id == "test-device-auth-id"

    # Explicit override still takes precedence
    auth_custom = MicrosoftDeviceAuth(client_id="explicit-override")
    assert auth_custom.client_id == "explicit-override"


def test_msa_flow_records_client_id(monkeypatch):
    monkeypatch.setenv("NLC_MSA_CLIENT_ID", "recorded-client-id-777")
    
    fake_auth = MagicMock()
    fake_auth.request_device_code.return_value = {
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/link",
        "device_code": "dev-code-123",
        "interval": 5,
        "expires_in": 900,
    }

    with patch("agent.MicrosoftDeviceAuth", return_value=fake_auth):
        res = handle_accounts_auth_microsoft_start({})
        assert res["status"] == "success"
        assert res["user_code"] == "ABCD-EFGH"
        assert res["verification_uri"] == "https://microsoft.com/link"
        assert res["client_id"] == "recorded-client-id-777"
