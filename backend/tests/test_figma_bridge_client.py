import pytest
import responses
from requests.exceptions import Timeout, ConnectionError
from src.config import settings
from src.services.figma_bridge_client import FigmaBridgeClient


def test_figma_bridge_settings():
    assert hasattr(settings, "SELLFORM_FIGMA_BRIDGE_URL")
    assert hasattr(settings, "SELLFORM_FIGMA_BRIDGE_TOKEN")
    assert hasattr(settings, "SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS")


@responses.activate
def test_figma_bridge_auth_required():
    client = FigmaBridgeClient()
    bridge_url = f"{settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip('/')}/v1/exports"
    
    responses.add(
        responses.POST,
        bridge_url,
        json={"error_code": "AUTH_REQUIRED", "error_message": "User needs authorization", "auth_url": "https://figma.com/oauth"},
        status=401
    )
    
    res = client.trigger_export(
        job_id="job-1",
        target_file_url="https://figma.com/design/xxx",
        payload={"dummy": "data"}
    )
    
    assert res["success"] is False
    assert res["error_code"] == "AUTH_REQUIRED"
    assert "auth_url" in res
    assert res["auth_url"] == "https://figma.com/oauth"


@responses.activate
def test_figma_bridge_timeout_to_mcp_unavailable():
    client = FigmaBridgeClient()
    bridge_url = f"{settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip('/')}/v1/exports"
    
    responses.add(
        responses.POST,
        bridge_url,
        body=Timeout("Connection timed out")
    )
    
    res = client.trigger_export(
        job_id="job-1",
        target_file_url="https://figma.com/design/xxx",
        payload={"dummy": "data"}
    )
    
    assert res["success"] is False
    assert res["error_code"] == "MCP_UNAVAILABLE"
    assert "timeout" in res["error_message"].lower()


@responses.activate
def test_figma_bridge_connection_error_to_mcp_unavailable():
    client = FigmaBridgeClient()
    bridge_url = f"{settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip('/')}/v1/exports"
    
    responses.add(
        responses.POST,
        bridge_url,
        body=ConnectionError("Failed to connect")
    )
    
    res = client.trigger_export(
        job_id="job-1",
        target_file_url="https://figma.com/design/xxx",
        payload={"dummy": "data"}
    )
    
    assert res["success"] is False
    assert res["error_code"] == "MCP_UNAVAILABLE"
