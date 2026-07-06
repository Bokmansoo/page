from typing import Any, Callable, Dict

from src.config import settings


class FigmaMcpAdapter:
    """Adapter for the payload-only Figma collaboration endpoint.

    Sprint 33 live exports use ``FigmaBridgeClient`` directly. This adapter
    remains intentionally sender-driven so it cannot silently pretend that a
    Figma export completed when no MCP sender is configured.
    """

    def __init__(
        self,
        sender: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.enabled = (
            settings.SELLFORM_FIGMA_MCP_ENABLED if enabled is None else enabled
        )
        self.sender = sender

    def export_to_figma(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "success": False,
                "status": "disabled",
                "reason": "Figma MCP 연동이 비활성화되어 있습니다.",
            }

        if self.sender is None:
            return {
                "success": False,
                "status": "not_configured",
                "reason": (
                    "Figma MCP sender is not configured. "
                    "Only the design payload was generated."
                ),
                "payload": payload,
            }

        try:
            result = self.sender(payload)
        except Exception as exc:
            return {
                "success": False,
                "status": "failed",
                "reason": f"Figma MCP export failed: {exc}",
            }

        return {
            "success": True,
            "status": "exported",
            "message": "The design payload was sent to the configured Figma MCP sender.",
            "result": result,
        }
