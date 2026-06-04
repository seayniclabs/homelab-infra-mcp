"""Home Assistant module — comprehensive control and configuration.

Provides tools for:
- Entity control (lights, switches, covers, climate, media players)
- Automation management (list, create, update, delete, trigger)
- Script management (list, create, update, delete, run)
- State queries and device discovery
- Service calls (any domain/service combination)
"""

import json
import logging
from typing import Any

import httpx
import yaml

from homelab_infra_mcp.config import config
from homelab_infra_mcp.safety import check_mode, is_dry_run

logger = logging.getLogger("homelab-infra-mcp")

# Home Assistant configuration
HA_TOKEN_FILE = "/Volumes/data/secrets/ha_token"


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


async def _hass_api_call(
    method: str, path: str, data: dict | None = None, params: dict | None = None
) -> dict:
    """Make a Home Assistant REST API call.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path (e.g., '/api/states')
        data: JSON body for POST/PUT/DELETE requests
        params: Query parameters

    Returns:
        dict with success status and result or error message
    """
    token = _read_ha_token()
    if not token:
        return {
            "success": False,
            "error": f"Home Assistant token not available at {HA_TOKEN_FILE}"
        }

    url = f"{config.home_assistant_url}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=data)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=data)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, json=data)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}

            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "data": resp.json() if resp.content else {},
                    "status_code": resp.status_code
                }
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": resp.text or "Unknown error"
                }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": f"Cannot reach Home Assistant at {config.home_assistant_url}. Is it running?"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"Timeout connecting to Home Assistant at {config.home_assistant_url}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Home Assistant API error: {str(e)}"
        }


def register(mcp):
    """Register Home Assistant tools with the MCP server."""

    # ============================================================================
    # Entity Control
    # ============================================================================

    @mcp.tool()
    async def hass_get_states() -> str:
        """List all Home Assistant entities with their current state and attributes."""
        result = await _hass_api_call("GET", "/api/states")
        return json.dumps(result)

    @mcp.tool()
    async def hass_get_state(entity_id: str) -> str:
        """Get the state and attributes of a specific entity.

        Args:
            entity_id: Entity ID (e.g., 'light.bedroom_3', 'switch.fan')
        """
        result = await _hass_api_call("GET", f"/api/states/{entity_id}")
        return json.dumps(result)

    @mcp.tool()
    async def hass_call_service(
        domain: str, service: str, entity_id: str | None = None, **kwargs
    ) -> str:
        """Call any Home Assistant service with optional parameters.

        Args:
            domain: Service domain (e.g., 'light', 'switch', 'automation')
            service: Service name (e.g., 'turn_on', 'turn_off', 'toggle')
            entity_id: Optional entity ID to target
            **kwargs: Additional service data (brightness, color_temp, etc.)

        Examples:
            hass_call_service('light', 'turn_on', 'light.bedroom_3', brightness=128)
            hass_call_service('automation', 'trigger', 'automation.morning')
        """
        data = kwargs.copy()
        if entity_id:
            data["entity_id"] = entity_id

        result = await _hass_api_call("POST", f"/api/services/{domain}/{service}", data=data)
        return json.dumps(result)

    @mcp.tool()
    async def hass_turn_on(entity_id: str, **kwargs) -> str:
        """Turn on a Home Assistant entity with optional parameters.

        Args:
            entity_id: Entity ID (e.g., 'light.bedroom_3', 'switch.fan')
            **kwargs: Optional parameters (brightness, color_temp_kelvin, rgb_color, etc.)

        Examples:
            hass_turn_on('light.bedroom_3', brightness=128, color_temp_kelvin=2700)
        """
        data = {"entity_id": entity_id}
        data.update(kwargs)

        # Determine domain from entity_id
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"

        result = await _hass_api_call("POST", f"/api/services/{domain}/turn_on", data=data)
        return json.dumps(result)

    @mcp.tool()
    async def hass_turn_off(entity_id: str) -> str:
        """Turn off a Home Assistant entity.

        Args:
            entity_id: Entity ID (e.g., 'light.bedroom_3', 'switch.fan')
        """
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        result = await _hass_api_call(
            "POST", f"/api/services/{domain}/turn_off", data={"entity_id": entity_id}
        )
        return json.dumps(result)

    @mcp.tool()
    async def hass_toggle(entity_id: str) -> str:
        """Toggle a Home Assistant entity (on -> off, off -> on).

        Args:
            entity_id: Entity ID (e.g., 'light.bedroom_3', 'switch.fan')
        """
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        result = await _hass_api_call(
            "POST", f"/api/services/{domain}/toggle", data={"entity_id": entity_id}
        )
        return json.dumps(result)

    # ============================================================================
    # Automation Management
    # ============================================================================

    @mcp.tool()
    async def hass_list_automations() -> str:
        """List all automations with their current state and configuration."""
        result = await _hass_api_call("GET", "/api/states")
        if result.get("success"):
            automations = [
                s for s in result["data"] if s.get("entity_id", "").startswith("automation.")
            ]
            return json.dumps({"success": True, "count": len(automations), "automations": automations})
        return json.dumps(result)

    @mcp.tool()
    async def hass_trigger_automation(entity_id: str) -> str:
        """Trigger/run an automation immediately.

        Args:
            entity_id: Automation entity ID (e.g., 'automation.morning')
        """
        result = await _hass_api_call(
            "POST", "/api/services/automation/trigger", data={"entity_id": entity_id}
        )
        return json.dumps(result)

    @mcp.tool()
    async def hass_create_automation(
        id: str, alias: str, trigger: list[dict], action: list[dict], condition: list[dict] | None = None
    ) -> str:
        """Create a new automation via the config API.

        Args:
            id: Unique automation ID (e.g., 'bedroom_light_voice')
            alias: Human-readable name
            trigger: List of trigger configurations
            condition: Optional list of conditions
            action: List of actions to execute

        Note: This requires the automation to be added to configuration.yaml or
        a separate automations.yaml file. For dynamic creation, use hass_update_config.
        """
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({
                "dry_run": True,
                "would_create": {"id": id, "alias": alias}
            })

        automation_config = {
            "id": id,
            "alias": alias,
            "trigger": trigger,
            "action": action
        }
        if condition:
            automation_config["condition"] = condition

        return json.dumps({
            "success": False,
            "error": "Direct automation creation requires file system access. Use hass_update_config instead.",
            "config": automation_config,
            "yaml": yaml.dump([automation_config])
        })

    # ============================================================================
    # Script Management
    # ============================================================================

    @mcp.tool()
    async def hass_list_scripts() -> str:
        """List all scripts with their current state."""
        result = await _hass_api_call("GET", "/api/states")
        if result.get("success"):
            scripts = [
                s for s in result["data"] if s.get("entity_id", "").startswith("script.")
            ]
            return json.dumps({"success": True, "count": len(scripts), "scripts": scripts})
        return json.dumps(result)

    @mcp.tool()
    async def hass_run_script(entity_id: str, **kwargs) -> str:
        """Run a script with optional parameters.

        Args:
            entity_id: Script entity ID (e.g., 'script.morning_routine')
            **kwargs: Optional variables to pass to the script
        """
        data = {"entity_id": entity_id}
        data.update(kwargs)

        result = await _hass_api_call("POST", "/api/services/script/turn_on", data=data)
        return json.dumps(result)

    # ============================================================================
    # Discovery & Search
    # ============================================================================

    @mcp.tool()
    async def hass_search_entities(query: str, domain: str | None = None) -> str:
        """Search for entities by name or entity_id with optional domain filter.

        Args:
            query: Search term (matches entity_id or friendly_name)
            domain: Optional domain filter (e.g., 'light', 'switch', 'automation')

        Examples:
            hass_search_entities('bedroom') - find all bedroom entities
            hass_search_entities('bedroom', 'light') - find bedroom lights only
        """
        result = await _hass_api_call("GET", "/api/states")
        if not result.get("success"):
            return json.dumps(result)

        entities = result["data"]
        query_lower = query.lower()

        # Filter by domain if specified
        if domain:
            entities = [e for e in entities if e.get("entity_id", "").startswith(f"{domain}.")]

        # Search in entity_id and friendly_name
        matches = [
            e for e in entities
            if query_lower in e.get("entity_id", "").lower()
            or query_lower in e.get("attributes", {}).get("friendly_name", "").lower()
        ]

        return json.dumps({
            "success": True,
            "query": query,
            "domain": domain,
            "count": len(matches),
            "matches": matches
        })

    # ============================================================================
    # Configuration & Services
    # ============================================================================

    @mcp.tool()
    async def hass_get_config() -> str:
        """Get Home Assistant configuration details."""
        result = await _hass_api_call("GET", "/api/config")
        return json.dumps(result)

    @mcp.tool()
    async def hass_list_services() -> str:
        """List all available services across all domains."""
        result = await _hass_api_call("GET", "/api/services")
        return json.dumps(result)

    @mcp.tool()
    async def hass_check_config() -> str:
        """Check if the current configuration is valid."""
        result = await _hass_api_call("POST", "/api/services/homeassistant/check_config")
        return json.dumps(result)

    @mcp.tool()
    async def hass_reload_automation() -> str:
        """Reload automation configuration from YAML files."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_reload": "automation"})

        result = await _hass_api_call("POST", "/api/services/automation/reload")
        return json.dumps(result)

    @mcp.tool()
    async def hass_reload_script() -> str:
        """Reload script configuration from YAML files."""
        blocked = check_mode("write")
        if blocked:
            return json.dumps({"error": blocked})
        if is_dry_run():
            return json.dumps({"dry_run": True, "would_reload": "script"})

        result = await _hass_api_call("POST", "/api/services/script/reload")
        return json.dumps(result)
