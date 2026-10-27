"""Start-and-list, module switches, missing config, the approval gate, and one mocked call per tool.

No test touches the network or a Docker engine: HTTP goes through httpx.MockTransport, and the
Docker SDK client is a fake passed in through the factory.
"""

from __future__ import annotations

import asyncio
import json
import sys

import docker as docker_sdk
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitResult

from homelab_infra_mcp.config import Config
from homelab_infra_mcp.server import build_server

PROXY = {"HOMELAB_PROXY_EMAIL": "admin@example.test", "HOMELAB_PROXY_PASSWORD": "pw-test"}
DNS = {"HOMELAB_DNS_API_TOKEN": "cf-test-token", "HOMELAB_DNS_ZONE_ID": "zone1"}
HA = {"HOMELAB_HOME_ASSISTANT_URL": "http://ha.test:8123", "HOMELAB_HOME_ASSISTANT_TOKEN": "ha-test"}

CORE_AND_MODULE_TOOLS = {
    "homelab_modules", "homelab_health", "expose_service", "teardown_service", "service_status",
    "infrastructure_overview", "proxy_hosts", "proxy_redirections", "proxy_certificates", "proxy_access_lists",
    "docker_containers", "docker_images", "docker_inventory", "dns_zones", "dns_records",
}
HA_TOOLS = {"ha_entities", "ha_automations", "ha_system"}


def factory(handler):
    """An HTTP client factory whose every request goes to ``handler`` (never the network)."""
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def no_http(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


def server(env, handler=no_http, docker=None):
    return build_server(Config(env=env, file_data={}), http=factory(handler),
                        docker=docker or (lambda host: FakeDocker()))


def tools(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


def call(mcp, tool_name, **args):
    """The structured result, or the tool's error raised."""
    _, structured = asyncio.run(mcp.call_tool(tool_name, args))
    return structured


def elicit_answer(approve: bool, action: str = "accept"):
    async def cb(context, params):
        return ElicitResult(action=action, content={"approve": approve} if action == "accept" else None)
    return cb


def call_with_client(mcp, name, args, elicitation=None):
    async def go():
        async with create_connected_server_and_client_session(mcp, elicitation_callback=elicitation) as client:
            return await client.call_tool(name, args)
    return asyncio.run(go())


# --- start, list, switches ---------------------------------------------------

def test_empty_env_starts_and_lists_core_and_default_modules():
    assert tools(server({})) == CORE_AND_MODULE_TOOLS


def test_home_assistant_is_opt_in():
    assert tools(server({"HOMELAB_HOME_ASSISTANT_ENABLED": "true"})) == CORE_AND_MODULE_TOOLS | HA_TOOLS
    assert not (tools(server({})) & HA_TOOLS)


def test_every_tool_has_an_output_schema():
    assert all(t.outputSchema for t in asyncio.run(server({}).list_tools()))


def test_module_switch_off_hides_its_tools():
    names = tools(server({"HOMELAB_DOCKER_ENABLED": "false"}))
    assert not any(n.startswith("docker_") for n in names)
    assert "proxy_hosts" in names


def test_config_file_is_read_and_env_wins():
    cfg = Config(env={"HOMELAB_PROXY_URL": "https://from-env.test"},
                 file_data={"proxy": {"url": "https://from-file.test", "email": "e@test"},
                            "docker": {"enabled": False}})
    assert cfg.get("proxy", "url") == "https://from-env.test"
    assert cfg.get("proxy", "email") == "e@test"
    assert cfg.enabled("docker", True) is False


def test_secret_can_come_from_a_file(tmp_path):
    token = tmp_path / "cf.token"
    token.write_text("from-file\n")
    cfg = Config(env={"HOMELAB_DNS_API_TOKEN_FILE": str(token)}, file_data={})
    assert cfg.get("dns", "api_token") == "from-file"


def test_homelab_modules_reports_missing_settings_and_hides_values():
    out = call(server({**DNS}), "homelab_modules")
    mods = {m["name"]: m for m in out["modules"]}
    assert mods["proxy"]["configured"] is False
    assert set(mods["proxy"]["missing"]) == {"HOMELAB_PROXY_EMAIL", "HOMELAB_PROXY_PASSWORD"}
    assert mods["dns"]["configured"] is True
    assert mods["home_assistant"]["enabled"] is False
    assert out["read_only"] is False and out["version"] == "2.0.0"


def test_homelab_modules_detail_never_leaks_secret_values():
    out = call(server({**DNS}), "homelab_modules", module="dns")
    assert "cf-test-token" not in json.dumps(out)
    settings = {s["env_var"]: s["set"] for s in out["modules"][0]["settings"]}
    assert settings["HOMELAB_DNS_API_TOKEN"] is True


# --- missing config never crashes; errors name the variable ---------------

@pytest.mark.parametrize("tool,args,needed", [
    ("proxy_hosts", {"action": "list"}, "HOMELAB_PROXY_EMAIL"),
    ("dns_zones", {}, "HOMELAB_DNS_API_TOKEN"),
    ("docker_containers", {"action": "list"}, None),  # socket default: no config needed, error comes from the engine
])
def test_unconfigured_tool_names_missing_variable(tool, args, needed):
    if needed is None:
        return
    with pytest.raises(Exception) as err:
        call(server({}), tool, **args)
    assert "not_configured" in str(err.value)
    assert needed in str(err.value)


def test_dns_records_without_zone_names_the_variable():
    with pytest.raises(Exception) as err:
        call(server({"HOMELAB_DNS_API_TOKEN": "t"}), "dns_records", action="list")
    assert "HOMELAB_DNS_ZONE_ID" in str(err.value)


def test_health_reports_missing_settings_without_crashing():
    out = call(server({}), "homelab_health")
    by = {m["module"]: m for m in out["modules"]}
    assert by["proxy"]["healthy"] is False and "HOMELAB_PROXY_EMAIL" in by["proxy"]["error"]
    assert by["dns"]["healthy"] is False and "HOMELAB_DNS_API_TOKEN" in by["dns"]["error"]
    assert by["home_assistant"]["enabled"] is False


# --- approval gate ----------------------------------------------------------

def test_write_without_approval_or_elicitation_fails_and_names_setting():
    with pytest.raises(Exception) as err:
        call(server(PROXY, npm_handler([])), "proxy_hosts", action="delete", host_id=1)
    text = str(err.value)
    assert "approval_unavailable" in text and "HOMELAB_PROXY_ALLOW_WRITES=true" in text


def test_read_only_refuses_even_pre_approved_writes():
    env = {**PROXY, "HOMELAB_READ_ONLY": "true", "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    with pytest.raises(Exception) as err:
        call(server(env, npm_handler([])), "proxy_hosts", action="delete", host_id=1)
    assert "read_only" in str(err.value)


def test_dry_run_previews_without_asking_or_calling_the_api():
    out = call(server(PROXY, no_http), "proxy_hosts", action="create", domain_names="app.example.test",
               forward_host="10.0.0.5", forward_port=8080, dry_run=True)
    assert out["change"]["dry_run"] is True and out["change"]["changed"] is False
    assert "app.example.test" in out["change"]["summary"]


def test_declined_by_person_changes_nothing():
    seen = []
    res = call_with_client(server(PROXY, npm_handler(seen)), "proxy_hosts",
                           {"action": "delete", "host_id": 1}, elicitation=elicit_answer(False))
    out = res.structuredContent
    assert out["change"]["changed"] is False
    assert "declined" in out["change"]["note"]
    assert not any(m == "DELETE" for m, _ in seen)
    assert ("GET", "/api/nginx/proxy-hosts/1") in seen


def test_person_approval_runs_the_change_and_records_who():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/tokens":
            return httpx.Response(200, json={"token": "t"})
        if req.method == "GET" and req.url.path.endswith("/proxy-hosts/3"):
            return httpx.Response(200, json={"id": 3, "domain_names": ["old.example.test"],
                                             "forward_host": "10.0.0.1", "forward_port": 80})
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(500)

    res = call_with_client(server(PROXY, handler), "proxy_hosts",
                           {"action": "delete", "host_id": 3}, elicitation=elicit_answer(True))
    change = res.structuredContent["change"]
    assert change["changed"] is True and change["approved_by"] == "person"
    assert ("DELETE", "/api/nginx/proxy-hosts/3") in seen


def test_elicitation_prompt_shows_the_exact_change():
    prompts = []

    async def cb(context, params):
        prompts.append(params.message)
        return ElicitResult(action="decline")

    def handler(req):
        if req.url.path == "/api/tokens":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(200, json={"id": 3, "domain_names": ["old.example.test"],
                                         "forward_host": "10.0.0.1", "forward_port": 80})

    call_with_client(server(PROXY, handler), "proxy_hosts", {"action": "delete", "host_id": 3}, elicitation=cb)
    assert prompts and "old.example.test" in prompts[0] and "Approve this change?" in prompts[0]


def test_preapproved_settings_skip_the_prompt():
    seen = []

    def handler(req):
        seen.append(req.method)
        if req.url.path == "/api/tokens":
            return httpx.Response(200, json={"token": "t"})
        if req.method == "GET":
            return httpx.Response(200, json={"id": 3, "domain_names": ["a.example.test"]})
        return httpx.Response(200, json={})

    out = call(server({**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}, handler), "proxy_hosts",
               action="delete", host_id=3)
    assert out["change"]["approved_by"] == "settings" and "DELETE" in seen


# --- proxy (NPM), mocked ------------------------------------------------------

def npm_handler(seen, hosts=None):
    hosts = hosts if hosts is not None else [
        {"id": 1, "domain_names": ["a.example.test"], "forward_host": "10.0.0.1", "forward_port": 80,
         "certificate_id": 0, "enabled": True},
        {"id": 2, "domain_names": ["b.example.test"], "forward_host": "10.0.0.2", "forward_port": 443,
         "certificate_id": 7, "enabled": True},
    ]

    def handle(req):
        seen.append((req.method, req.url.path))
        path = req.url.path
        if path == "/api/tokens":
            return httpx.Response(200, json={"token": "tok"})
        assert req.headers["authorization"] == "Bearer tok"
        if req.method == "GET" and path == "/api/nginx/proxy-hosts":
            return httpx.Response(200, json=hosts)
        if req.method == "GET" and path == "/api/nginx/proxy-hosts/1":
            return httpx.Response(200, json=hosts[0])
        if req.method == "POST" and path == "/api/nginx/proxy-hosts":
            return httpx.Response(201, json={"id": 9})
        if req.method == "PUT":
            return httpx.Response(200, json={"id": 1})
        if req.method == "DELETE":
            return httpx.Response(200, json={})
        if path == "/api/nginx/redirection-hosts" and req.method == "GET":
            return httpx.Response(200, json=[{"id": 4, "domain_names": ["old.example.test"],
                                              "forward_domain_name": "new.example.test", "forward_scheme": "https",
                                              "preserve_path": True}])
        if path == "/api/nginx/redirection-hosts" and req.method == "POST":
            return httpx.Response(201, json={"id": 5})
        if path == "/api/nginx/redirection-hosts/4":
            return httpx.Response(200, json={})
        if path == "/api/nginx/certificates" and req.method == "GET":
            return httpx.Response(200, json=[{"id": 7, "domain_names": ["b.example.test"], "provider": "letsencrypt",
                                              "expires_on": "2027-01-01"}])
        if path == "/api/nginx/certificates" and req.method == "POST":
            return httpx.Response(201, json={"id": 8})
        if path == "/api/nginx/access-lists" and req.method == "GET":
            return httpx.Response(200, json=[{"id": 2, "name": "lan"}])
        if path == "/api/nginx/access-lists" and req.method == "POST":
            return httpx.Response(201, json={"id": 3})
        if path == "/api/nginx/access-lists/2":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": "not found"})
    return handle


def test_proxy_hosts_list_pages_and_maps_fields():
    seen = []
    out = call(server(PROXY, npm_handler(seen)), "proxy_hosts", action="list", limit=1)
    assert out["total"] == 2 and out["has_more"] is True
    assert out["items"][0] == {"id": 1, "domains": ["a.example.test"], "forward_host": "10.0.0.1",
                               "forward_port": 80, "ssl": False, "enabled": True}
    assert seen[0] == ("POST", "/api/tokens")


def test_proxy_hosts_get_returns_full_record():
    out = call(server(PROXY, npm_handler([])), "proxy_hosts", action="get", host_id=1)
    assert out["detail"]["forward_port"] == 80


def test_proxy_hosts_create_with_pre_approval():
    seen = []
    env = {**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    out = call(server(env, npm_handler(seen)), "proxy_hosts", action="create", domain_names="app.example.test",
               forward_host="10.0.0.5", forward_port=8080)
    assert out["change"]["changed"] is True and out["change"]["id"] == "9"
    assert ("POST", "/api/nginx/proxy-hosts") in seen


def test_proxy_hosts_update_changes_only_forward_fields():
    seen = []
    env = {**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    out = call(server(env, npm_handler(seen)), "proxy_hosts", action="update", host_id=1, forward_port=8081)
    assert out["change"]["changed"] is True
    assert ("PUT", "/api/nginx/proxy-hosts/1") in seen


def test_proxy_hosts_rejects_bad_domain_before_any_call():
    with pytest.raises(Exception) as err:
        call(server(PROXY, npm_handler([])), "proxy_hosts", action="create", domain_names="not a domain",
             forward_host="10.0.0.5", forward_port=8080, dry_run=True)
    assert "bad_input" in str(err.value)


def test_proxy_auth_failure_is_reported():
    def handle(req):
        return httpx.Response(401, json={"message": "Invalid credentials"})
    with pytest.raises(Exception) as err:
        call(server(PROXY, handle), "proxy_hosts", action="list")
    assert "auth_failed" in str(err.value)


def test_proxy_redirections_list_and_create_dry_run():
    seen = []
    out = call(server(PROXY, npm_handler(seen)), "proxy_redirections", action="list")
    assert out["items"][0]["forward_domain"] == "new.example.test"
    dry = call(server(PROXY, npm_handler([])), "proxy_redirections", action="create",
               domain_names="old.example.test", forward_domain="new.example.test", dry_run=True)
    assert dry["change"]["dry_run"] is True


def test_proxy_redirections_delete_with_pre_approval():
    seen = []
    env = {**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    call(server(env, npm_handler(seen)), "proxy_redirections", action="delete", redirection_id=4)
    assert ("DELETE", "/api/nginx/redirection-hosts/4") in seen


def test_proxy_certificates_list_and_request():
    seen = []
    env = {**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    out = call(server(env, npm_handler(seen)), "proxy_certificates", action="list")
    assert out["items"][0]["expires_on"] == "2027-01-01"
    call(server(env, npm_handler(seen)), "proxy_certificates", action="request", domain_names="c.example.test")
    assert ("POST", "/api/nginx/certificates") in seen


def test_proxy_access_lists_list_and_create():
    seen = []
    env = {**PROXY, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    assert call(server(env, npm_handler(seen)), "proxy_access_lists", action="list")["items"][0]["name"] == "lan"
    out = call(server(env, npm_handler(seen)), "proxy_access_lists", action="create", name="office",
               allow="203.0.113.0/24", deny="0.0.0.0/0")
    assert out["change"]["summary"].endswith("2 rule(s)")
    assert ("POST", "/api/nginx/access-lists") in seen


# --- docker, with a fake engine ---------------------------------------------------

class FakeImage:
    tags = ["nginx:latest"]
    short_id = "sha256:img1"
    attrs = {"Size": 10485760}


class FakeContainer:
    def __init__(self, name="web", status="running"):
        self.name = name
        self.status = status
        self.short_id = "c0ffee123456"
        self.id = "c0ffee1234567890abcdef"
        self.ports = {"80/tcp": [{"HostPort": "8080"}]}
        self.image = FakeImage()
        self.attrs = {"Id": self.id, "Name": f"/{name}"}
        self.calls: list = []

    def start(self):
        self.calls.append("start")

    def stop(self, timeout=10):
        self.calls.append(("stop", timeout))

    def restart(self, timeout=10):
        self.calls.append(("restart", timeout))

    def remove(self):
        self.calls.append("remove")

    def logs(self, **kwargs):
        return b"2026-10-27T10:00:00Z hello\n2026-10-27T10:00:01Z world\n"

    def stats(self, stream=False):
        return {"cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 1000},
                "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
                "memory_stats": {"usage": 104857600, "limit": 209715200}}


class FakeContainers:
    def __init__(self):
        self.items = {"web": FakeContainer("web"), "old": FakeContainer("old", status="exited")}

    def list(self, all=False):
        return [c for c in self.items.values() if all or c.status == "running"]

    def get(self, ref):
        if ref in self.items:
            return self.items[ref]
        raise docker_sdk.errors.NotFound("no such container", explanation=f"No such container: {ref}")

    def prune(self):
        return {"ContainersDeleted": ["old"], "SpaceReclaimed": 0}


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()
        self.images = type("I", (), {})()
        self.images.list = lambda: [FakeImage()]
        self.images.pull = lambda image, tag: None
        self.images.remove = lambda image, force=False: None
        self.images.prune = lambda: {"SpaceReclaimed": 2048}
        self.volumes = type("V", (), {})()
        self.volumes.list = lambda: [type("Vol", (), {"name": "data", "attrs": {"Driver": "local"}})()]
        self.networks = type("N", (), {})()
        self.networks.list = lambda: [type("Net", (), {"short_id": "n1", "name": "bridge",
                                                       "attrs": {"Driver": "bridge"}})()]

    def info(self):
        return {"ServerVersion": "27.0", "Containers": 2, "ContainersRunning": 1, "Images": 1}


def test_docker_containers_list_and_get():
    out = call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="list", all=True)
    assert out["total"] == 2
    assert {"name": "web", "status": "running", "image": "nginx:latest", "id": "c0ffee123456", "ports": ["8080->80/tcp"]} \
        in out["items"]
    got = call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="get", container="web")
    assert got["items"][0]["name"] == "web"


def test_docker_container_logs_and_stats():
    logs = call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="logs", container="web", tail=1)
    assert logs["logs"] == ["2026-10-27T10:00:01Z world"]
    stats = call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="stats", container="web")
    assert stats["stats"]["memory_percent"] == 50.0 and stats["stats"]["cpu_percent"] == 20.0


def test_docker_stop_needs_approval_and_runs_when_pre_approved():
    fake = FakeDocker()
    env = {"HOMELAB_DOCKER_ALLOW_WRITES": "true"}
    out = call(server(env, docker=lambda h: fake), "docker_containers", action="stop", container="web", timeout=5)
    assert out["change"]["changed"] is True and ("stop", 5) in fake.containers.items["web"].calls


def test_docker_remove_without_approval_is_refused():
    with pytest.raises(Exception) as err:
        call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="remove", container="old")
    assert "HOMELAB_DOCKER_ALLOW_WRITES=true" in str(err.value)


def test_docker_prune_dry_run_changes_nothing():
    fake = FakeDocker()
    out = call(server({}, docker=lambda h: fake), "docker_containers", action="prune", dry_run=True)
    assert out["change"]["dry_run"] is True and "old" in fake.containers.items


def test_docker_missing_container_is_reported():
    with pytest.raises(Exception) as err:
        call(server({}, docker=lambda h: FakeDocker()), "docker_containers", action="get", container="nope")
    assert "homelab.docker.not_found" in str(err.value)


def test_docker_images_and_inventory():
    fake = FakeDocker()
    imgs = call(server({}, docker=lambda h: fake), "docker_images", action="list")
    assert imgs["items"][0]["tags"] == ["nginx:latest"]
    vols = call(server({}, docker=lambda h: fake), "docker_inventory", kind="volumes")
    assert vols["items"][0]["name"] == "data"
    nets = call(server({}, docker=lambda h: fake), "docker_inventory", kind="networks")
    assert nets["items"][0]["driver"] == "bridge"


def test_docker_stacks_need_portainer():
    with pytest.raises(Exception) as err:
        call(server({}, docker=lambda h: FakeDocker()), "docker_inventory", kind="stacks")
    assert "HOMELAB_DOCKER_PORTAINER_URL" in str(err.value)


def test_portainer_backend_lists_containers_over_mocked_http():
    env = {"HOMELAB_DOCKER_PORTAINER_URL": "https://portainer.test", "HOMELAB_DOCKER_PORTAINER_TOKEN": "pt"}
    seen = []

    def handle(req):
        seen.append((req.method, req.url.path, req.headers.get("x-api-key")))
        return httpx.Response(200, json=[{"Id": "abc123def456789", "Names": ["/web"], "State": "running",
                                          "Image": "nginx", "Ports": []}])
    out = call(server(env, handle), "docker_containers", action="list")
    assert out["items"][0]["name"] == "web"
    assert seen[0] == ("GET", "/api/endpoints/1/docker/containers/json", "pt")


# --- dns (Cloudflare), mocked -------------------------------------------------

def cf_handler(seen, writes_ok=True):
    records = [{"id": "r1", "type": "A", "name": "app.example.test", "content": "192.0.2.1",
                "proxied": False, "ttl": 1}]

    def handle(req):
        seen.append((req.method, req.url.path))
        if req.headers.get("authorization") != "Bearer cf-test-token":
            return httpx.Response(401, json={"success": False, "errors": [{"message": "bad token"}]})
        p = req.url.path
        if p.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"result": {"status": "active"}})
        if p == "/client/v4/zones":
            return httpx.Response(200, json={"result": [{"id": "zone1", "name": "example.test", "status": "active",
                                                         "name_servers": ["ns.test"]}],
                                             "result_info": {"total_pages": 1}})
        if p == "/client/v4/zones/zone1/dns_records/export":
            return httpx.Response(200, text="$ORIGIN example.test.\n")
        if p == "/client/v4/zones/zone1/dns_records" and req.method == "GET":
            return httpx.Response(200, json={"result": records, "result_info": {"total_pages": 1}})
        if p == "/client/v4/zones/zone1/dns_records" and req.method == "POST":
            return httpx.Response(200, json={"result": {"id": "r2"}})
        if p == "/client/v4/zones/zone1/dns_records/r1" and req.method == "GET":
            return httpx.Response(200, json={"result": records[0]})
        if p == "/client/v4/zones/zone1/dns_records/r1" and req.method == "PUT":
            return httpx.Response(200, json={"result": {"id": "r1"}})
        if p == "/client/v4/zones/zone1/dns_records/r1" and req.method == "DELETE":
            return httpx.Response(200, json={"result": {"id": "r1"}})
        return httpx.Response(404, json={"errors": [{"message": "no such record"}]})
    return handle


def test_dns_zones_list_and_export():
    seen = []
    out = call(server(DNS, cf_handler(seen)), "dns_zones", action="list")
    assert out["zones"][0]["name"] == "example.test"
    exp = call(server(DNS, cf_handler(seen)), "dns_zones", action="export")
    assert exp["export"].startswith("$ORIGIN")


def test_dns_records_list_filters_and_get():
    seen = []
    out = call(server(DNS, cf_handler(seen)), "dns_records", action="list", record_type="a")
    assert out["items"][0] == {"id": "r1", "type": "A", "name": "app.example.test", "content": "192.0.2.1",
                               "proxied": False, "ttl": 1}
    got = call(server(DNS, cf_handler(seen)), "dns_records", action="get", record_id="r1")
    assert got["detail"]["content"] == "192.0.2.1"


def test_dns_create_dry_run_then_pre_approved():
    seen = []
    dry = call(server(DNS, cf_handler(seen)), "dns_records", action="create", name="x.example.test",
               record_type="CNAME", content="t.example.net", dry_run=True)
    assert dry["change"]["dry_run"] is True and ("POST", "/client/v4/zones/zone1/dns_records") not in seen
    env = {**DNS, "HOMELAB_DNS_ALLOW_WRITES": "true"}
    out = call(server(env, cf_handler(seen)), "dns_records", action="create", name="x.example.test",
               record_type="CNAME", content="t.example.net")
    assert out["change"]["id"] == "r2"


def test_dns_update_and_delete_pre_approved():
    seen = []
    env = {**DNS, "HOMELAB_DNS_ALLOW_WRITES": "true"}
    call(server(env, cf_handler(seen)), "dns_records", action="update", record_id="r1", content="192.0.2.9")
    assert ("PUT", "/client/v4/zones/zone1/dns_records/r1") in seen
    call(server(env, cf_handler(seen)), "dns_records", action="delete", record_id="r1")
    assert ("DELETE", "/client/v4/zones/zone1/dns_records/r1") in seen


def test_dns_bad_token_is_reported():
    with pytest.raises(Exception) as err:
        call(server({**DNS, "HOMELAB_DNS_API_TOKEN": "wrong"}, cf_handler([])), "dns_zones", action="list")
    assert "auth_failed" in str(err.value)


def test_dns_rejects_unsupported_record_type_before_any_call():
    with pytest.raises(Exception) as err:
        call(server(DNS, cf_handler([])), "dns_records", action="list", record_type="PTR")
    assert "bad_input" in str(err.value)


# --- home assistant, mocked (opt-in) ----------------------------------------

def ha_handler(seen):
    states = [{"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen light"}},
              {"entity_id": "automation.morning", "state": "on", "attributes": {"friendly_name": "Morning"}}]

    def handle(req):
        seen.append((req.method, req.url.path))
        p = req.url.path
        if p == "/api/states":
            return httpx.Response(200, json=states)
        if p == "/api/config":
            return httpx.Response(200, json={"version": "2026.10"})
        if p.startswith("/api/services/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, text="nope")
    return handle


HA_ENV = {**HA, "HOMELAB_HOME_ASSISTANT_ENABLED": "true"}


def test_ha_entities_search_and_get():
    seen = []
    out = call(server(HA_ENV, ha_handler(seen)), "ha_entities", action="search", query="kitchen")
    assert out["items"][0]["entity_id"] == "light.kitchen"
    got = call(server(HA_ENV, ha_handler(seen)), "ha_entities", action="get", entity_id="light.kitchen")
    assert got["detail"]["state"] == "off"


def test_ha_turn_on_needs_approval():
    with pytest.raises(Exception) as err:
        call(server(HA_ENV, ha_handler([])), "ha_entities", action="turn_on", entity_id="light.kitchen")
    assert "HOMELAB_HOME_ASSISTANT_ALLOW_WRITES=true" in str(err.value)


def test_ha_turn_on_pre_approved_calls_service():
    seen = []
    env = {**HA_ENV, "HOMELAB_HOME_ASSISTANT_ALLOW_WRITES": "true"}
    out = call(server(env, ha_handler(seen)), "ha_entities", action="turn_on", entity_id="light.kitchen")
    assert out["change"]["changed"] is True
    assert ("POST", "/api/services/light/turn_on") in seen


def test_ha_automation_create_only_returns_yaml():
    seen = []
    out = call(server(HA_ENV, ha_handler(seen)), "ha_automations", action="create", automation_id="porch",
               alias="Porch light", triggers=[{"trigger": "sun", "event": "sunset"}],
               actions=[{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}])
    assert "alias: Porch light" in out["yaml"]
    assert all(m == "GET" for m, _ in seen)


def test_ha_system_config_is_read_only():
    out = call(server(HA_ENV, ha_handler([])), "ha_system", action="config")
    assert out["data"]["version"] == "2026.10"


# --- health and cross-module workflows ------------------------------------

def test_homelab_health_probes_enabled_modules():
    def handle(req):
        if req.url.path == "/api/":
            return httpx.Response(200, json={})
        if req.url.path == "/client/v4/user/tokens/verify":
            return httpx.Response(200, json={"result": {"status": "active"}})
        return httpx.Response(500)
    env = {**PROXY, **DNS}
    out = call(server(env, handle, docker=lambda h: FakeDocker()), "homelab_health")
    by = {m["module"]: m for m in out["modules"]}
    assert by["dns"]["healthy"] is True and by["proxy"]["healthy"] is True and by["docker"]["healthy"] is True


def test_expose_service_dry_run_lists_plan_only():
    out = call(server({**PROXY, **DNS}, no_http, docker=lambda h: FakeDocker()), "expose_service",
               container_name="web", domain="web.example.test", forward_port=8080,
               tunnel_hostname="tunnel.example.net", dry_run=True)
    assert out["dry_run"] is True and len(out["planned"]) == 3
    assert "create CNAME web.example.test -> tunnel.example.net (proxied)" in out["planned"]


def test_expose_service_pre_approved_runs_dns_and_proxy():
    seen = []
    env = {**PROXY, **DNS, "HOMELAB_PROXY_ALLOW_WRITES": "true", "HOMELAB_DNS_ALLOW_WRITES": "true"}

    def handle(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/tokens":
            return httpx.Response(200, json={"token": "tok"})
        if req.url.path.endswith("/dns_records"):
            return httpx.Response(200, json={"result": {"id": "rx"}})
        return httpx.Response(201, json={"id": 11})

    out = call(server(env, handle, docker=lambda h: FakeDocker()), "expose_service",
               container_name="web", domain="web.example.test", forward_port=8080,
               tunnel_hostname="tunnel.example.net")
    assert out["success"] is True and out["approved_by"] == "settings"
    assert ("POST", "/client/v4/zones/zone1/dns_records") in seen or any("dns_records" in p for _, p in seen)
    assert ("POST", "/api/nginx/proxy-hosts") in seen


def test_teardown_service_plans_and_deletes_with_pre_approval():
    seen = []
    env = {**PROXY, **DNS, "HOMELAB_PROXY_ALLOW_WRITES": "true"}
    out = call(server(env, npm_handler(seen)), "teardown_service", domain="a.example.test")
    assert out["planned"] == ["DELETE proxy host 1 (a.example.test)"]
    assert ("DELETE", "/api/nginx/proxy-hosts/1") in seen


def test_service_status_and_overview():
    env = {**PROXY, **DNS}

    def handle(req):
        if req.url.path == "/api/tokens":
            return httpx.Response(200, json={"token": "tok"})
        if req.url.path == "/api/nginx/proxy-hosts":
            return httpx.Response(200, json=[{"id": 1, "domain_names": ["web.example.test"]}])
        if req.url.path == "/client/v4/zones/zone1/dns_records":
            return httpx.Response(200, json={"result": [{"id": "r1", "type": "A", "name": "web.example.test",
                                                         "content": "192.0.2.1"}], "result_info": {"total_pages": 1}})
        return httpx.Response(500)

    status = call(server(env, handle, docker=lambda h: FakeDocker()), "service_status",
                  container_name="web", domain="web.example.test")
    assert status["container"]["name"] == "web"
    assert status["proxy_hosts"][0]["id"] == 1 and status["dns_records"][0]["id"] == "r1"
    overview = call(server(env, handle, docker=lambda h: FakeDocker()), "infrastructure_overview")
    assert overview["proxy"]["proxy_hosts"] == 1 and overview["dns"]["by_type"] == {"A": 1}


# --- stdio, empty environment -------------------------------------------------

def test_stdio_start_with_empty_env_reports_package_version(tmp_path):
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "homelab_infra_mcp"],
                                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                listed = await session.list_tools()
                return init.serverInfo.version, {t.name for t in listed.tools}
    version, names = asyncio.run(go())
    assert version == "2.0.0"
    assert names == CORE_AND_MODULE_TOOLS
