"""Homelab 2.1: four opt-in modules (uptime, tunnel, dns_filter, sso), diagnose_service, the approval log,
skills served as prompts, and --doctor. Every HTTP call goes through httpx.MockTransport; nothing touches
the network or a Docker engine."""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest
from mcp.types import ElicitResult

from homelab_infra_mcp import doctor
from homelab_infra_mcp.config import Config
from homelab_infra_mcp import diagnose
from homelab_infra_mcp.modules.uptime import parse_monitor_status
from homelab_infra_mcp.server import build_server

ALL_ON = {
    "HOMELAB_UPTIME_ENABLED": "true", "HOMELAB_UPTIME_URL": "http://kuma.test:3001",
    "HOMELAB_UPTIME_API_KEY": "kuma-key",
    "HOMELAB_TUNNEL_ENABLED": "true", "HOMELAB_TUNNEL_API_TOKEN": "cf-tunnel-test",
    "HOMELAB_TUNNEL_ACCOUNT_ID": "a" * 32, "HOMELAB_TUNNEL_TUNNEL_ID": "b" * 32,
    "HOMELAB_DNS_FILTER_ENABLED": "true", "HOMELAB_DNS_FILTER_URL": "http://adguard.test:3000",
    "HOMELAB_DNS_FILTER_USERNAME": "admin", "HOMELAB_DNS_FILTER_PASSWORD": "pw-test",
    "HOMELAB_SSO_ENABLED": "true", "HOMELAB_SSO_URL": "https://auth.test", "HOMELAB_SSO_TOKEN": "sso-test",
    "HOMELAB_PROXY_EMAIL": "admin@example.test", "HOMELAB_PROXY_PASSWORD": "pw-test",
    "HOMELAB_DNS_API_TOKEN": "cf-test-token", "HOMELAB_DNS_ZONE_ID": "0" * 32,
}
NEW_TOOLS = {"uptime_monitors", "tunnel_routes", "dns_filter_status", "dns_filter_queries",
             "dns_filter_rules", "sso_applications"}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """The approval log defaults to ~/.local/state; keep tests out of the real home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def no_http(request):
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


def server(env, handler=no_http, docker=None, **kw):
    return build_server(Config(env=env, file_data={}), http=factory(handler),
                        docker=docker or (lambda host: None), **kw)


def tool_names(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


def call(mcp, name, **args):
    _, structured = asyncio.run(mcp.call_tool(name, args))
    return structured


def approve_with(answer: bool):
    async def cb(context, params):
        return ElicitResult(action="accept", content={"approve": answer})
    return cb


def call_eliciting(mcp, name, args, answer: bool):
    from mcp.shared.memory import create_connected_server_and_client_session

    async def go():
        async with create_connected_server_and_client_session(mcp, elicitation_callback=approve_with(answer)) as c:
            return await c.call_tool(name, args)
    return asyncio.run(go())


# --- switches -----------------------------------------------------------------

def test_new_modules_are_off_by_default():
    names = tool_names(server({}))
    assert not (NEW_TOOLS & names)
    assert "diagnose_service" in names


def test_each_new_module_switches_on_with_its_switch():
    assert {"uptime_monitors"} <= tool_names(server({"HOMELAB_UPTIME_ENABLED": "true"}))
    assert {"tunnel_routes"} <= tool_names(server({"HOMELAB_TUNNEL_ENABLED": "true"}))
    assert {"dns_filter_status", "dns_filter_queries", "dns_filter_rules"} <= tool_names(
        server({"HOMELAB_DNS_FILTER_ENABLED": "true"}))
    assert {"sso_applications"} <= tool_names(server({"HOMELAB_SSO_ENABLED": "true"}))


# --- uptime ---------------------------------------------------------------------

METRICS = """# HELP monitor_status Monitor Status
# TYPE monitor_status gauge
monitor_status{monitor_id="1",monitor_name="Blog",monitor_type="http",monitor_url="https://blog.example.test",monitor_hostname=""} 1
monitor_status{monitor_id="2",monitor_name="Wiki",monitor_type="http",monitor_url="https://wiki.example.test",monitor_hostname=""} 0
monitor_status{monitor_id="3",monitor_name="Nas",monitor_type="ping",monitor_url="",monitor_hostname="nas.lan"} 2
"""


def test_parse_monitor_status_reads_prometheus_labels_and_states():
    rows = parse_monitor_status(METRICS)
    assert [(r.id, r.name, r.status) for r in rows] == [("1", "Blog", "up"), ("2", "Wiki", "down"),
                                                       ("3", "Nas", "pending")]
    assert rows[0].url == "https://blog.example.test"
    assert rows[2].hostname == "nas.lan"


def test_uptime_list_filters_by_status_and_sends_basic_auth_with_api_key():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, text=METRICS)

    mcp = server({**ALL_ON, "HOMELAB_UPTIME_ENABLED": "true"}, handler)
    out = call(mcp, "uptime_monitors", action="list", status="down")
    assert [m["name"] for m in out["items"]] == ["Wiki"]
    assert seen["path"] == "/metrics"
    assert seen["auth"].startswith("Basic ")


def test_uptime_metrics_off_names_the_setting_to_turn_on():
    mcp = server({**ALL_ON, "HOMELAB_UPTIME_ENABLED": "true"}, lambda r: httpx.Response(404))
    with pytest.raises(Exception, match="Prometheus API"):
        call(mcp, "uptime_monitors", action="list")


def test_uptime_get_unknown_monitor_is_not_found():
    mcp = server({**ALL_ON, "HOMELAB_UPTIME_ENABLED": "true"}, lambda r: httpx.Response(200, text=METRICS))
    with pytest.raises(Exception, match="no monitor with id 99"):
        call(mcp, "uptime_monitors", action="get", monitor_id="99")


# --- tunnel -----------------------------------------------------------------------

def tunnel_handler(seen, ingress):
    state = {"ingress": list(ingress)}

    def handler(request):
        path = request.url.path
        if request.method == "GET" and path.endswith("/cfd_tunnel"):
            return httpx.Response(200, json={"result": [{"id": "b" * 32, "name": "home", "status": "healthy"}]})
        if path.endswith("/configurations") and request.method == "GET":
            return httpx.Response(200, json={"result": {"config": {"ingress": state["ingress"]}}})
        if path.endswith("/configurations") and request.method == "PUT":
            body = json.loads(request.content)
            seen.append(body)
            state["ingress"] = body["config"]["ingress"]
            return httpx.Response(200, json={"result": {}})
        raise AssertionError(f"unexpected {request.method} {path}")
    return handler


TUNNEL_ENV = {**ALL_ON, "HOMELAB_TUNNEL_ENABLED": "true"}
CATCH_ALL = {"service": "http_status:404"}


def test_tunnel_list_shows_tunnels_and_routes():
    seen: list = []
    mcp = server(TUNNEL_ENV, tunnel_handler(seen, [{"hostname": "app.example.test", "service": "http://nginx:80"},
                                                   CATCH_ALL]))
    out = call(mcp, "tunnel_routes", action="list")
    assert out["tunnels"][0]["name"] == "home"
    assert out["routes"][0]["hostname"] == "app.example.test"


def test_tunnel_add_dry_run_keeps_catch_all_last_and_changes_nothing():
    seen: list = []
    mcp = server(TUNNEL_ENV, tunnel_handler(seen, [CATCH_ALL]))
    out = call(mcp, "tunnel_routes", action="add", hostname="new.example.test", service="http://web:8080",
               dry_run=True)
    assert out["change"]["dry_run"] is True
    assert out["change"]["detail"]["ingress"][-1] == CATCH_ALL
    assert out["change"]["detail"]["ingress"][0] == {"hostname": "new.example.test", "service": "http://web:8080"}
    assert seen == []


def test_tunnel_add_without_approval_is_refused_and_names_setting():
    mcp = server(TUNNEL_ENV, tunnel_handler([], [CATCH_ALL]))
    with pytest.raises(Exception, match="HOMELAB_TUNNEL_ALLOW_WRITES"):
        call(mcp, "tunnel_routes", action="add", hostname="new.example.test", service="http://web:8080")


def test_tunnel_add_with_person_approval_puts_full_config():
    seen: list = []
    mcp = server({k: v for k, v in TUNNEL_ENV.items()}, tunnel_handler(seen, [CATCH_ALL]))
    res = call_eliciting(mcp, "tunnel_routes", {"action": "add", "hostname": "new.example.test",
                                                "service": "http://web:8080"}, answer=True)
    assert not res.isError
    assert seen[0]["config"]["ingress"][-1] == CATCH_ALL
    assert {"hostname": "new.example.test", "service": "http://web:8080"} in seen[0]["config"]["ingress"]


def test_tunnel_remove_unknown_host_is_not_found_and_bad_origin_refused():
    mcp = server({**TUNNEL_ENV, "HOMELAB_TUNNEL_ALLOW_WRITES": "true"}, tunnel_handler([], [CATCH_ALL]))
    with pytest.raises(Exception, match="no route for gone.example.test"):
        call(mcp, "tunnel_routes", action="remove", hostname="gone.example.test")
    with pytest.raises(Exception, match="not a valid origin"):
        call(mcp, "tunnel_routes", action="add", hostname="x.example.test", service="ftp://nope")


# --- dns filter -------------------------------------------------------------------

def adguard_handler(seen, rules=None):
    state = {"rules": list(rules or [])}

    def handler(request):
        p = request.url.path
        assert request.headers["authorization"].startswith("Basic ")
        if p == "/control/status":
            return httpx.Response(200, json={"running": True, "version": "v0.107.0"})
        if p == "/control/stats":
            return httpx.Response(200, json={"num_dns_queries": 10, "num_blocked_filtering": 2})
        if p == "/control/querylog":
            return httpx.Response(200, json={"data": [
                {"time": "t1", "client": "10.0.0.5", "question": {"name": "ads.example.test", "type": "A"},
                 "reason": "FilteredBlackList"},
                {"time": "t2", "client": "10.0.0.5", "question": {"name": "ok.example.test", "type": "A"},
                 "reason": "NotFilteredNotFound"}]})
        if p == "/control/filtering/status":
            return httpx.Response(200, json={"enabled": True, "user_rules": state["rules"]})
        if p == "/control/blocked_services/list":
            return httpx.Response(200, json=["youtube"])
        if p == "/control/filtering/set_rules":
            body = json.loads(request.content)
            seen.append(body)
            state["rules"] = body["rules"]
            return httpx.Response(200)
        raise AssertionError(f"unexpected {request.method} {p}")
    return handler


DNS_ENV = {**ALL_ON, "HOMELAB_DNS_FILTER_ENABLED": "true"}


def test_dns_filter_status_and_blocked_queries_only():
    mcp = server(DNS_ENV, adguard_handler([]))
    st = call(mcp, "dns_filter_status")
    assert st["status"]["version"] == "v0.107.0"
    q = call(mcp, "dns_filter_queries", blocked_only=True)
    assert [r["domain"] for r in q["items"]] == ["ads.example.test"]
    assert q["items"][0]["blocked"] is True


def test_dns_filter_add_rule_rewrites_whole_list_and_rejects_multiline():
    seen: list = []
    mcp = server({**DNS_ENV, "HOMELAB_DNS_FILTER_ALLOW_WRITES": "true"}, adguard_handler(seen, ["||old.test^"]))
    out = call(mcp, "dns_filter_rules", action="add", rule="||tracker.example.test^")
    assert seen[0] == {"rules": ["||old.test^", "||tracker.example.test^"]}
    assert out["change"]["changed"] is True
    with pytest.raises(Exception, match="one non-empty line"):
        call(mcp, "dns_filter_rules", action="add", rule="||a.test^\n||b.test^")


def test_dns_filter_remove_missing_rule_is_not_found():
    mcp = server({**DNS_ENV, "HOMELAB_DNS_FILTER_ALLOW_WRITES": "true"}, adguard_handler([], []))
    with pytest.raises(Exception, match="not in the custom list"):
        call(mcp, "dns_filter_rules", action="remove", rule="||none.test^")


# --- sso ---------------------------------------------------------------------------

def authentik_handler(seen):
    def handler(request):
        p = request.url.path
        if p == "/api/v3/flows/instances/" and request.url.params.get("slug"):
            return httpx.Response(200, json={"results": [{"pk": "flow-auth-uuid"}]})
        if p == "/api/v3/flows/instances/" and request.url.params.get("designation") == "invalidation":
            return httpx.Response(200, json={"results": [{"pk": "flow-inv-uuid"}]})
        if p == "/api/v3/providers/proxy/" and request.method == "POST":
            seen.append(("provider", json.loads(request.content)))
            return httpx.Response(201, json={"pk": 7, "name": "Blog"})
        if p == "/api/v3/core/applications/" and request.method == "POST":
            seen.append(("app", json.loads(request.content)))
            return httpx.Response(201, json={"pk": "app-uuid"})
        if p == "/api/v3/core/applications/":
            return httpx.Response(200, json={"results": [{"pk": "app-uuid", "name": "Blog", "slug": "blog",
                                                         "provider": 7}]})
        if p == "/api/v3/providers/proxy/":
            return httpx.Response(200, json={"results": [{"pk": 7, "name": "Blog",
                                                         "external_host": "https://blog.example.test",
                                                         "mode": "forward_single"}]})
        raise AssertionError(f"unexpected {request.method} {p}")
    return handler


SSO_ENV = {**ALL_ON, "HOMELAB_SSO_ENABLED": "true"}


def test_sso_list_reads_apps_and_providers():
    out = call(server(SSO_ENV, authentik_handler([])), "sso_applications", action="list")
    assert out["applications"][0]["slug"] == "blog"
    assert out["providers"][0]["external_host"] == "https://blog.example.test"


def test_sso_create_dry_run_makes_no_calls():
    seen: list = []
    out = call(server(SSO_ENV, authentik_handler(seen)), "sso_applications", action="create",
               host="blog.example.test", dry_run=True)
    assert out["change"]["dry_run"] is True and out["change"]["detail"]["slug"] == "blog-example-test"
    assert seen == []


def test_sso_create_with_preapproval_creates_provider_then_application():
    seen: list = []
    mcp = server({**SSO_ENV, "HOMELAB_SSO_ALLOW_WRITES": "true"}, authentik_handler(seen))
    out = call(mcp, "sso_applications", action="create", host="blog.example.test")
    assert out["change"]["changed"] is True
    (kind1, body1), (kind2, body2) = seen
    assert kind1 == "provider" and body1["authorization_flow"] == "flow-auth-uuid"
    assert body1["invalidation_flow"] == "flow-inv-uuid" and body1["external_host"] == "https://blog.example.test"
    assert kind2 == "app" and body2 == {"name": "blog.example.test", "slug": "blog-example-test", "provider": 7}


# --- diagnose_service -------------------------------------------------------------

def npm_hosts_handler(hosts):
    def handler(request):
        p = request.url.path
        if p == "/api/tokens":
            return httpx.Response(200, json={"token": "t"})
        if p.endswith("nginx/proxy-hosts"):
            return httpx.Response(200, json=hosts)
        raise AssertionError(f"unexpected {p}")
    return handler


def test_diagnose_reports_missing_proxy_host_as_first_failure(monkeypatch):
    monkeypatch.setattr(diagnose.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("203.0.113.9", 443))])
    env = {**ALL_ON, "HOMELAB_TUNNEL_ENABLED": "false", "HOMELAB_DOCKER_ENABLED": "false",
           "HOMELAB_DNS_FILTER_ENABLED": "false", "HOMELAB_SSO_ENABLED": "false",
           "HOMELAB_UPTIME_ENABLED": "false"}
    mcp = server(env, npm_hosts_handler([]))
    out = call(mcp, "diagnose_service", domain="blog.example.test")
    hops = {h["hop"]: h for h in out["hops"]}
    assert [h["hop"] for h in out["hops"]] == diagnose.HOPS
    assert hops["dns"]["status"] == "ok"
    assert out["first_failure"] == "proxy"
    assert "expose_service" in hops["proxy"]["fix"]
    assert hops["uptime"]["status"] == "skipped"


def test_diagnose_dns_failure_is_first_and_read_only(monkeypatch):
    def boom(*a, **k):
        raise OSError("nodename nor servname provided")
    monkeypatch.setattr(diagnose.socket, "getaddrinfo", boom)
    env = {**ALL_ON, "HOMELAB_TUNNEL_ENABLED": "false", "HOMELAB_DOCKER_ENABLED": "false",
           "HOMELAB_DNS_FILTER_ENABLED": "false", "HOMELAB_SSO_ENABLED": "false", "HOMELAB_UPTIME_ENABLED": "false"}
    mcp = server(env, npm_hosts_handler([{"id": 3, "domain_names": ["gone.example.test"], "enabled": True}]))
    out = call(mcp, "diagnose_service", domain="gone.example.test")
    assert out["first_failure"] == "dns"
    assert out["hops"][0]["fix"]


def test_diagnose_is_listed_as_read_only():
    tool = {t.name: t for t in asyncio.run(server({}).list_tools())}["diagnose_service"]
    assert tool.annotations.readOnlyHint is True


# --- approval log --------------------------------------------------------------------

def test_approval_log_records_decline_without_request_body(tmp_path):
    log = tmp_path / "approvals.jsonl"
    mcp = server({**TUNNEL_ENV, "HOMELAB_APPROVAL_LOG": str(log)}, tunnel_handler([], [CATCH_ALL]))
    res = call_eliciting(mcp, "tunnel_routes", {"action": "add", "hostname": "new.example.test",
                                                "service": "http://web:8080"}, answer=False)
    assert "declined" in str(res.content[0].text).lower() or res.isError is False
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["decision"] for line in lines] == ["requested", "declined"]
    assert lines[0]["tool"] == "tunnel.add"
    assert "new.example.test" in lines[0]["summary"]
    assert set(lines[0]) == {"ts", "tool", "decision", "approved_by", "summary"}


def test_approval_log_records_refusal_when_read_only(tmp_path):
    log = tmp_path / "approvals.jsonl"
    mcp = server({**TUNNEL_ENV, "HOMELAB_APPROVAL_LOG": str(log), "HOMELAB_READ_ONLY": "true",
                  "HOMELAB_TUNNEL_ALLOW_WRITES": "true"}, tunnel_handler([], [CATCH_ALL]))
    with pytest.raises(Exception, match="read_only"):
        call(mcp, "tunnel_routes", action="add", hostname="x.example.test", service="http://web:8080")
    assert json.loads(log.read_text().splitlines()[0])["decision"] == "refused"


def test_approval_log_records_settings_approval(tmp_path):
    log = tmp_path / "approvals.jsonl"
    seen: list = []
    mcp = server({**TUNNEL_ENV, "HOMELAB_APPROVAL_LOG": str(log), "HOMELAB_TUNNEL_ALLOW_WRITES": "true"},
                 tunnel_handler(seen, [CATCH_ALL]))
    call(mcp, "tunnel_routes", action="add", hostname="y.example.test", service="http://web:8080")
    line = json.loads(log.read_text().splitlines()[0])
    assert line["decision"] == "approved" and line["approved_by"] == "settings"


# --- skills and discovery -----------------------------------------------------------

EXPECTED_SKILLS = {"getting-started", "expose-a-service-safely", "homelab-health-check", "containers", "runbook",
                   "homelab-troubleshooting", "fix-and-deploy", "diagram", "network-diagram",
                   "systematic-debugging", "cloudflare", "cloudflare-one", "dashmotion", "architecture-diagram"}


def test_every_skill_is_a_prompt_and_resources_exist():
    mcp = server({})
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert EXPECTED_SKILLS <= prompts
    resources = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
    assert "skill://homelab/getting-started/SKILL.md" in resources


def test_discovery_lists_skills_publisher_and_homepage():
    out = call(server({}), "homelab_modules")
    assert {s["name"] for s in out["skills"]} >= EXPECTED_SKILLS
    assert out["publisher"] == "Seaynic Labs"
    assert out["homepage"] == "https://github.com/seayniclabs/homelab-infra-mcp"


def test_no_promotion_reaches_the_model():
    mcp = server(ALL_ON)
    texts = [mcp.instructions or ""]
    texts += [t.description or "" for t in asyncio.run(mcp.list_tools())]
    for p in asyncio.run(mcp.list_prompts()):
        texts.append(asyncio.run(mcp.get_prompt(p.name)).messages[0].content.text)
    for text in texts:
        assert "seayniclabs.com" not in text.lower()


def test_skill_bodies_carry_no_internal_plumbing():
    mcp = server({})
    banned = re.compile("|".join(["/Vol" "umes", "helms" "man", "CM" "DB", "192\\.168\\.", "Char" "lie", "Bri" "dge"]), re.I)
    for p in asyncio.run(mcp.list_prompts()):
        assert not banned.search(asyncio.run(mcp.get_prompt(p.name)).messages[0].content.text), p.name


# --- doctor ---------------------------------------------------------------------------

def test_doctor_exits_1_with_fix_lines_when_settings_missing(capsys):
    code = doctor.run(Config(env={}, file_data={}))
    out = capsys.readouterr().out
    assert code == 1
    assert "FIX" in out and "HOMELAB_PROXY_EMAIL" in out


def test_doctor_exits_0_when_every_enabled_module_is_off(capsys):
    env = {"HOMELAB_PROXY_ENABLED": "false", "HOMELAB_DOCKER_ENABLED": "false", "HOMELAB_DNS_ENABLED": "false"}
    assert doctor.run(Config(env=env, file_data={})) == 0
    assert "ready" in capsys.readouterr().out


def test_doctor_reports_docker_socket_missing(capsys, tmp_path):
    env = {"HOMELAB_PROXY_ENABLED": "false", "HOMELAB_DNS_ENABLED": "false",
           "HOMELAB_DOCKER_HOST": f"unix://{tmp_path}/missing.sock"}
    assert doctor.run(Config(env=env, file_data={})) == 1
    assert "Docker socket" in capsys.readouterr().out


# --- stdio subprocess: read every reply before closing stdin -------------------------

def _exchange(proc, msgs, timeout=60):
    """Send messages, then read replies until every request id has answered. Closing stdin first
    races the server's shutdown against its last reply on fast machines."""
    import subprocess  # noqa: F401  (proc is a subprocess.Popen)
    import time
    for m in msgs:
        proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
    want = {m["id"] for m in msgs if "id" in m}
    replies, end = {}, time.time() + timeout
    while want - set(replies) and time.time() < end:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("id") is not None:
            replies[r["id"]] = r
    proc.stdin.close()
    proc.kill()
    proc.wait()
    return replies


def test_stdio_subprocess_lists_tools_and_prompts(tmp_path):
    import os
    import subprocess
    import sys

    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, "-m", "homelab_infra_mcp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "probe", "version": "0"}}}
    msgs = [init,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}}]
    replies = _exchange(proc, msgs)
    assert replies[1]["result"]["serverInfo"]["version"] == "2.1.0"
    tool_names = {t["name"] for t in replies[2]["result"]["tools"]}
    assert "diagnose_service" in tool_names and "uptime_monitors" not in tool_names
    prompt_names = {p["name"] for p in replies[3]["result"]["prompts"]}
    assert "getting-started" in prompt_names
