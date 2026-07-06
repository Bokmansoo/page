import pytest
from src.services.figma_mcp_adapter import FigmaMcpAdapter


def test_figma_mcp_adapter_disabled():
    adapter = FigmaMcpAdapter(enabled=False)
    res = adapter.export_to_figma({"key": "val"})
    assert res["success"] is False
    assert "연동" in res["reason"] or "비활성화" in res["reason"]


def test_figma_mcp_adapter_enabled_without_sender_does_not_claim_delivery():
    adapter = FigmaMcpAdapter(enabled=True)
    res = adapter.export_to_figma({"key": "val"})
    assert res["success"] is False
    assert res["status"] == "not_configured"


def test_figma_mcp_adapter_enabled_uses_injected_sender():
    sent_payloads = []

    def sender(payload):
        sent_payloads.append(payload)
        return {"file_url": "https://figma.com/design/example"}

    adapter = FigmaMcpAdapter(sender=sender, enabled=True)
    res = adapter.export_to_figma({"key": "val"})

    assert res["success"] is True
    assert res["status"] == "exported"
    assert res["result"]["file_url"] == "https://figma.com/design/example"
    assert sent_payloads == [{"key": "val"}]


def test_figma_mcp_adapter_reports_sender_failure():
    def failing_sender(_payload):
        raise RuntimeError("connection refused")

    adapter = FigmaMcpAdapter(sender=failing_sender, enabled=True)
    res = adapter.export_to_figma({"key": "val"})

    assert res["success"] is False
    assert res["status"] == "failed"
    assert "connection refused" in res["reason"]
