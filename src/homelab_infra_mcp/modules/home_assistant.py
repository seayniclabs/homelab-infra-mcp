"""Home Assistant module — 2 tools for turning entities on and off."""

import json
import logging

import httpx

logger = logging.getLogger("homelab-infra-mcp")

# Home Assistant configuration
HA_HOST = "homeassistant.local"
HA_PORT = 8123
HA_URL = f"http://{HA_HOST}:{HA_PORT}"
HA_TOKEN_FILE = "/Volumes/data/secrets/homepage_ha_token"


def _read_ha_token() -> str | None:
    """Read HA token from file. Returns None if file not found."""
    try:
        with open(HA_TOKEN_FILE, "r") as f:
            token = f.read().strip()
            return token if token else None
    except FileNotFoundError:
        logger.warning(f"HA token file not found: {HA_TOKEN_FILE}")
        return None
    except Exception as e:
        logger.error(f"Failed to read HA token: {e}")
        return None


async def _hass_service_call(service: str, entity_id: str) -> dict:
    """Call a Home Assistant service.

    Args:
        service: Service name (turn_on or turn_off)
        entity_id: Entity ID (e.g., 'light.living_room')

    Returns:
        dict with success status and result or error message
    """
    token = _read_ha_token()
    if not token:
        return {
            "success": False,
            "error": f"Home Assistant token not available at {HA_TOKEN_FILE}"
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{HA_URL}/api/services/homeassistant/{service}",
                json={"entity_id": entity_id},
                headers={"Authorization": f"Bearer {token}"}
            )

            if resp.status_code == 200:
                data = resp.json()
                # Home Assistant returns a list of state objects
                state = data[0] if isinstance(data, list) and len(data) > 0 else {}
                return {
                    "success": True,
                    "entity_id": entity_id,
                    "service": service,
                    "state": state.get("state", "unknown"),
                }
            else:
                return {
                    "success": False,
                    "entity_id": entity_id,
                    "status_code": resp.status_code,
                    "error": resp.text or "Unknown error"
                }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": f"Cannot reach Home Assistant at {HA_URL}. Is it running?"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"Timeout connecting to Home Assistant at {HA_URL}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Home Assistant API error: {str(e)}"
        }


def register(mcp):
    """Register Home Assistant tools with the MCP server."""

    @mcp.tool()
    async def hass_turn_on(entity_id: str) -> str:
        """Turn on a Home Assistant entity (light, switch, etc.) by entity_id.

        Args:
            entity_id: Entity ID to turn on (e.g., 'light.living_room', 'switch.fan')
        """
        result = await _hass_service_call("turn_on", entity_id)
        return json.dumps(result)

    @mcp.tool()
    async def hass_turn_off(entity_id: str) -> str:
        """Turn off a Home Assistant entity (light, switch, etc.) by entity_id.

        Args:
            entity_id: Entity ID to turn off (e.g., 'light.living_room', 'switch.fan')
        """
        result = await _hass_service_call("turn_off", entity_id)
        return json.dumps(result)
