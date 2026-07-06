import logging
import requests
from requests.exceptions import Timeout, RequestException
from src.config import settings

logger = logging.getLogger(__name__)


class FigmaBridgeClient:
    def __init__(self):
        self.base_url = settings.SELLFORM_FIGMA_BRIDGE_URL.rstrip("/")
        self.token = settings.SELLFORM_FIGMA_BRIDGE_TOKEN
        self.timeout = settings.SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS

    def trigger_export(self, job_id: str, target_file_url: str, payload: dict) -> dict:
        url = f"{self.base_url}/v1/exports"
        headers = {
            "Content-Type": "application/json",
        }
        if self.token:
            headers["X-Sellform-Bridge-Token"] = self.token

        body = {
            "job_id": job_id,
            "target_file_url": target_file_url,
            "payload": payload
        }

        try:
            resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            
            # If 401 Unauthorized, check if bridge sent a structured auth URL
            if resp.status_code == 401:
                try:
                    data = resp.json()
                    if data.get("error_code") == "AUTH_REQUIRED":
                        return {
                            "success": False,
                            "error_code": "AUTH_REQUIRED",
                            "error_message": data.get("error_message", "Authentication required"),
                            "auth_url": data.get("auth_url")
                        }
                except ValueError:
                    pass
                return {
                    "success": False,
                    "error_code": "AUTH_DENIED",
                    "error_message": "Figma bridge unauthorized or credentials invalid."
                }

            try:
                data = resp.json()
            except ValueError:
                return {
                    "success": resp.status_code == 200,
                    "error_code": "RENDER_FAILED" if resp.status_code != 200 else None,
                    "error_message": f"Non-JSON response (status: {resp.status_code})"
                }

            if resp.status_code == 200:
                result_file_url = data.get("result_file_url")
                result_node_url = data.get("result_node_url")
                if not result_file_url or not result_node_url:
                    return {
                        "success": False,
                        "error_code": "INVALID_MCP_RESPONSE",
                        "error_message": "Figma Bridge did not return validated result URLs."
                    }
                return {
                    "success": True,
                    "result_file_url": result_file_url,
                    "result_node_url": result_node_url
                }
            else:
                return {
                    "success": False,
                    "error_code": data.get("error_code") or "RENDER_FAILED",
                    "error_message": data.get("error_message") or f"Bridge export failed with status {resp.status_code}"
                }

        except Timeout as te:
            logger.error("Timeout connecting to Figma Bridge: %s", te)
            return {
                "success": False,
                "error_code": "MCP_UNAVAILABLE",
                "error_message": f"Connection timed out (timeout: {self.timeout}s). Figma MCP is unavailable."
            }
        except RequestException as re:
            logger.error("Failed to call Figma Bridge: %s", re)
            return {
                "success": False,
                "error_code": "MCP_UNAVAILABLE",
                "error_message": f"Figma Bridge service connection error: {str(re)}"
            }
