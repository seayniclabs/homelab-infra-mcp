# NAS Module Design Specification (nas.py)
**Component:** `homelab-infra-mcp`  
**Target Hardware:** UGREEN DXP4800 Plus (Intel Pentium Gold 8505)  
**Operating System:** UGOS Pro 1.17 (Debian 12 base)  
**Status:** Approved Design (Phase 2)  
**Author:** AI Agent (Task #147293)  
**Date:** 2026-10-29  

---

## 1. Overview & Objectives

The `nas` module adds first-class support for Network Attached Storage devices to `homelab-infra-mcp`, starting with the primary homelab storage appliance: the **UGREEN DXP4800 Plus** running **UGOS Pro 1.17** (`192.168.68.68`).

### Objectives
1. **Unified Observability:** Provide agents and human operators complete visibility into NAS health, system utilization, storage pools, volumes, physical disks, SMART telemetry, network shares, background services, and scheduled tasks.
2. **Safe Mutability:** Allow lifecycle control over network shares (SMB/NFS), core system services, and scheduled tasks behind the server's mandatory approval flow (`approval.py` and `run_change`).
3. **Dual-Channel Integration:** Leverage the native UGOS Pro REST API (`/ugreen/v1/...`) for standard operational tasks, combined with a strictly sandboxed SSH helper for deep diagnostic metrics (such as detailed `smartctl` and `nvme-cli` telemetry) that the web API abstracts away.
4. **Zero-Trust Safety & Hygiene:** Adhere to `homelab-infra-mcp` core design principles:
   - Opt-in by default (`HOMELAB_NAS_ENABLED=false`).
   - File-backed secrets (`HOMELAB_NAS_PASSWORD_FILE`).
   - Dry-run preview on all mutating tools (`dry_run=true`).
   - Comprehensive structured outputs matching published Pydantic models.
   - Consistent error formats (`homelab.nas.<code>: <message> Fix: <hint>`).

---

## 2. Architecture & Module Structure

The module follows the standard `homelab-infra-mcp` integration contract defined in `homelab_infra_mcp.modules.Module`.

```
homelab-infra-mcp/
├── src/homelab_infra_mcp/
│   ├── modules/
│   │   ├── __init__.py           # Registers NasModule in all_modules()
│   │   └── nas.py                # NasModule, NasClient, NasSshClient, tool functions
│   ├── config.py                 # Configuration loader (supports env, _FILE, config.toml)
│   ├── runtime.py                # Runtime.nas() client factory
│   ├── doctor.py                 # Health probe for `homelab doctor`
│   └── models.py                 # Shared Change, page, run_change
├── docs/
│   ├── nas-module-design.md      # This document
│   └── ugos-api.md               # Reverse-engineered UGOS endpoint specifications
└── tests/
    └── test_nas.py               # Mocked HTTP & SSH unit test suite
```

### Module Registration Contract
In `src/homelab_infra_mcp/modules/__init__.py`:
```python
@dataclass
class NasModule(Module):
    def __init__(self) -> None:
        super().__init__(
            name="nas",
            summary="UGREEN NAS health, storage pools, shares, services, and scheduled tasks.",
            default_enabled=False,  # Always opt-in
            settings=[
                Setting("url", "UGOS Pro base address. Default https://192.168.68.68:9443", required=False),
                Setting("user", "UGOS API username with monitoring/management permissions.", required=True),
                Setting("password", "UGOS API user password.", secret=True, required=True),
                Setting("ssh_host", "Optional SSH host/IP for low-level SMART/CLI inspection. Defaults to url host.", required=False),
                Setting("ssh_user", "SSH username (default charlieseay).", required=False),
                Setting("ssh_key_file", "Path to SSH private key (default ~/.ssh/id_ugreen).", required=False),
                Setting("ssh_port", "SSH port (default 22).", required=False),
                Setting("verify_ssl", "Whether to verify SSL certificates on port 9443 (default false).", required=False),
                ALLOW_WRITES,
            ],
            tools={
                "nas_status": "System health, CPU/RAM utilization, temps, fan speeds, uptime, and network interfaces.",
                "nas_storage": "Storage pools, volumes, physical drives, and SMART health diagnostics.",
                "nas_shares": "List, inspect, create, update, or remove SMB and NFS network shares.",
                "nas_services": "List, inspect, restart, enable, or disable NAS core system services.",
                "nas_tasks": "List, inspect, trigger, enable, or disable scheduled system and backup tasks.",
            },
        )
```

---

## 3. Tool Function Specifications

All tools return structured Pydantic models inheriting from `BaseModel`. List endpoints implement pagination via `page(items, limit, offset)`. Mutating operations accept `dry_run: bool = False` and wrap actions in `run_change`.

### 3.1. `nas_status` (Read-Only)
Inspects system-level health, hardware telemetry, and network link states.

- **Annotations:** `readOnlyHint=True, openWorldHint=False`
- **Signature:**
  ```python
  async def nas_status(
      ctx: Context,
      action: Literal["overview", "system", "network", "hardware"] = "overview",
  ) -> NasStatusResult
  ```
- **Result Schema:**
  ```python
  class SystemOverview(BaseModel):
      model: str                      # e.g., "UGREEN DXP4800 Plus"
      serial_number: str
      ugos_version: str               # e.g., "UGOS Pro 1.17"
      uptime_seconds: int
      cpu_model: str                  # e.g., "Intel Pentium Gold 8505"
      cpu_usage_percent: float
      memory_total_mb: float
      memory_used_mb: float
      memory_usage_percent: float

  class NetworkInterface(BaseModel):
      name: str                       # e.g., "eth0", "eth1" (2.5GbE / 10GbE)
      mac_address: str
      ip_addresses: list[str]
      speed_mbps: int | None
      duplex: str | None
      rx_bytes: int
      tx_bytes: int
      link_up: bool

  class HardwareSensors(BaseModel):
      cpu_temp_c: float
      system_temp_c: float
      fan_speeds_rpm: list[int]
      power_status: str

  class NasStatusResult(BaseModel):
      action: str
      system: SystemOverview | None = None
      network: list[NetworkInterface] | None = None
      hardware: HardwareSensors | None = None
  ```
- **UGOS Endpoints / SSH Fallbacks:**
  - `GET /ugreen/v1/sys/info` -> Model, serial, OS version, uptime.
  - `GET /ugreen/v1/sys/utilization` -> CPU, RAM, and sensor temps.
  - `GET /ugreen/v1/net/interfaces` -> Network configuration and link stats.
  - SSH fallback: `/proc/loadavg`, `/proc/meminfo`, `ip -j addr`, `ip -j link`.

---

### 3.2. `nas_storage` (Read-Only)
Comprehensive view of storage hierarchy: Storage Pools (RAID/ZFS/Btrfs), Volumes (filesystem capacity), Physical Drives (HDD/NVMe), and SMART health.

- **Annotations:** `readOnlyHint=True, openWorldHint=False`
- **Signature:**
  ```python
  async def nas_storage(
      ctx: Context,
      action: Literal["overview", "pools", "volumes", "disks", "smart"] = "overview",
      disk_id: str = "",
      limit: int = 20,
      offset: int = 0,
  ) -> NasStorageResult
  ```
- **Result Schema:**
  ```python
  class StoragePool(BaseModel):
      pool_id: str
      name: str
      raid_type: str                  # Basic, RAID0, RAID1, RAID5, RAID6, ZFS mirror/raidz
      status: str                     # "normal", "degraded", "rebuilding"
      total_bytes: int
      used_bytes: int
      member_disks: list[str]

  class StorageVolume(BaseModel):
      volume_id: str                  # e.g., "volume1"
      name: str
      fs_type: str                    # "btrfs", "ext4", "zfs"
      path: str                       # "/volume1"
      status: str
      total_bytes: int
      used_bytes: int
      free_bytes: int
      usage_percent: float

  class PhysicalDisk(BaseModel):
      disk_id: str                    # e.g., "drive1", "nvme0n1"
      slot: int
      device_node: str                # "/dev/sda", "/dev/nvme0n1"
      model: str
      serial: str
      capacity_bytes: int
      disk_type: str                  # "HDD", "SSD", "NVMe"
      temperature_c: int | None
      health_status: str              # "healthy", "warning", "failing"

  class SmartAttribute(BaseModel):
      id: int
      name: str
      raw_value: int
      normalized_value: int
      worst_value: int
      threshold: int
      status: str

  class SmartHealth(BaseModel):
      disk_id: str
      overall_status: str             # "passed", "failed"
      power_on_hours: int | None
      reallocated_sectors: int | None
      temperature_c: int | None
      attributes: list[SmartAttribute] = []
      nvme_wear_percent: int | None = None

  class NasStorageResult(BaseModel):
      action: str
      pools: list[StoragePool] = []
      volumes: list[StorageVolume] = []
      disks: list[PhysicalDisk] = []
      smart: SmartHealth | None = None
      total: int | None = None
      has_more: bool = False
  ```
- **UGOS Endpoints / SSH Fallbacks:**
  - `GET /ugreen/v1/storage/pools` -> Pool statuses and members.
  - `GET /ugreen/v1/storage/volumes` -> Volume capacities and mount points.
  - `GET /ugreen/v1/storage/disks` -> Physical disk inventory and health summaries.
  - `GET /ugreen/v1/storage/disks/{id}/smart` -> SMART attributes.
  - SSH fallback: `smartctl -a /dev/...` or `nvme smart-log /dev/...` for granular NVMe percentage used, TBW (terabytes written), and SMART error logs.

---

### 3.3. `nas_shares` (Read & Write with Approval)
Manages network-accessible shares (SMB, NFS). Creation, modification, and deletion alter host configuration and require approval.

- **Annotations:** `readOnlyHint=False, destructiveHint=True, openWorldHint=False`
- **Signature:**
  ```python
  async def nas_shares(
      ctx: Context,
      action: Literal["list", "get", "create", "update", "delete"] = "list",
      share_name: str = "",
      path: str = "",
      protocol: Literal["all", "smb", "nfs"] = "all",
      comment: str = "",
      read_only: bool = False,
      guest_ok: bool = False,
      allowed_users: list[str] | None = None,
      allowed_hosts: list[str] | None = None,  # for NFS exports
      limit: int = 20,
      offset: int = 0,
      dry_run: bool = False,
  ) -> NasSharesResult
  ```
- **Result Schema:**
  ```python
  class ShareItem(BaseModel):
      name: str
      path: str                       # e.g., "/volume1/backups"
      protocols: list[str]            # ["smb", "nfs"]
      comment: str | None = None
      read_only: bool = False
      guest_ok: bool = False
      allowed_users: list[str] = []
      allowed_hosts: list[str] = []

  class NasSharesResult(BaseModel):
      items: list[ShareItem] = []
      detail: dict[str, Any] | None = None
      total: int | None = None
      has_more: bool = False
      change: Change | None = None
  ```
- **Validation Rules (`validation.py`):**
  - `share_name`: Regex `^[a-zA-Z0-9_\-]+$`, maximum 64 characters, disallows reserved names (`IPC$`, `ADMIN$`, `global`).
  - `path`: Must be an absolute volume path (e.g. `/volume1/...`), rejecting relative paths or directory traversal (`..`, `//`).

---

### 3.4. `nas_services` (Read & Write with Approval)
Monitors and controls system daemons running on the NAS (Samba, NFS, SSH, WebDAV, Rsync, Docker daemon).

- **Annotations:** `readOnlyHint=False, destructiveHint=True, openWorldHint=False`
- **Signature:**
  ```python
  async def nas_services(
      ctx: Context,
      action: Literal["list", "get", "restart", "enable", "disable"] = "list",
      service: str = "",
      limit: int = 20,
      offset: int = 0,
      dry_run: bool = False,
  ) -> NasServicesResult
  ```
- **Result Schema:**
  ```python
  class NasServiceItem(BaseModel):
      name: str                       # e.g., "smb", "nfs", "ssh", "webdav", "docker"
      display_name: str
      enabled: bool
      running: bool
      port: int | None = None
      details: dict[str, Any] | None = None

  class NasServicesResult(BaseModel):
      items: list[NasServiceItem] = []
      detail: dict[str, Any] | None = None
      total: int | None = None
      has_more: bool = False
      change: Change | None = None
  ```
- **Allowed Services:** `smb`, `nfs`, `ssh`, `webdav`, `rsync`, `ftp`, `docker`.
- **Approval Gate:** Mutating operations (`restart`, `enable`, `disable`) require approval. `restart` warns about active client disconnections.

---

### 3.5. `nas_tasks` (Read & Write with Approval)
Inspects and manages scheduled maintenance tasks, backup jobs, RAID scrubbing, and SMART surface tests.

- **Annotations:** `readOnlyHint=False, destructiveHint=True, openWorldHint=False`
- **Signature:**
  ```python
  async def nas_tasks(
      ctx: Context,
      action: Literal["list", "get", "history", "run", "enable", "disable"] = "list",
      task_id: str = "",
      limit: int = 20,
      offset: int = 0,
      dry_run: bool = False,
  ) -> NasTasksResult
  ```
- **Result Schema:**
  ```python
  class TaskHistoryItem(BaseModel):
      execution_id: str
      task_id: str
      start_time: str
      end_time: str | None
      status: str                     # "success", "failed", "running"
      exit_code: int | None
      log_snippet: str | None

  class NasTaskItem(BaseModel):
      task_id: str
      name: str
      task_type: str                  # "scrubbing", "smart_test", "backup", "script"
      enabled: bool
      cron_schedule: str | None
      next_run: str | None
      last_run_status: str | None

  class NasTasksResult(BaseModel):
      items: list[NasTaskItem] = []
      detail: dict[str, Any] | None = None
      history: list[TaskHistoryItem] = []
      total: int | None = None
      has_more: bool = False
      change: Change | None = None
  ```
- **Approval Gate:** `run` (triggers task immediately), `enable`, and `disable` change execution state and require approval.

---

## 4. Configuration Settings & Secret Management

All settings comply with `homelab_infra_mcp.config` conventions.

| Environment Variable | Config Table `[nas]` | Type | Default | Description |
|---|---|---|---|---|
| `HOMELAB_NAS_ENABLED` | `enabled` | bool | `false` | Enables the NAS module. |
| `HOMELAB_NAS_URL` | `url` | string | `https://192.168.68.68:9443` | Base URL of UGOS Pro web interface / API. |
| `HOMELAB_NAS_USER` | `user` | string | *required* | Username for UGOS Pro API authentication. |
| `HOMELAB_NAS_PASSWORD` | `password` | string (secret) | *required* | Password for UGOS Pro API user. |
| `HOMELAB_NAS_PASSWORD_FILE` | *n/a* | filepath | *none* | Path to password file (e.g. `/Volumes/data/secrets/ugreen_nas_password`). |
| `HOMELAB_NAS_VERIFY_SSL` | `verify_ssl` | bool | `false` | Verify TLS cert (set false for self-signed appliance certs). |
| `HOMELAB_NAS_SSH_HOST` | `ssh_host` | string | Host from URL | Optional SSH host address for CLI-backed inspection. |
| `HOMELAB_NAS_SSH_USER` | `ssh_user` | string | `charlieseay` | Username for SSH access. |
| `HOMELAB_NAS_SSH_KEY_FILE`| `ssh_key_file` | filepath | `~/.ssh/id_ugreen` | Private key file for SSH authentication. |
| `HOMELAB_NAS_SSH_PORT` | `ssh_port` | int | `22` | SSH port. |
| `HOMELAB_NAS_ALLOW_WRITES`| `allow_writes` | bool | `false` | When true, bypasses manual confirmation for write actions. |

### Config TOML Example (`~/.config/homelab/config.toml`)
```toml
[nas]
enabled = true
url = "https://192.168.68.68:9443"
user = "agent_reader"
password = "super-secret-nas-password"
ssh_host = "192.168.68.68"
ssh_user = "charlieseay"
ssh_key_file = "~/.ssh/id_ugreen"
verify_ssl = false
allow_writes = false
```

### Secret Loading & Redaction
- Evaluated via `config.get("nas", "password")`, which automatically checks `HOMELAB_NAS_PASSWORD_FILE` if `HOMELAB_NAS_PASSWORD` is absent.
- Password strings are marked with `Setting(..., secret=True)`.
- Passwords and SSH private keys are never printed in logs, exception strings, or tool outputs.

---

## 5. Write Action Approval Flows

In accordance with `homelab_infra_mcp.approval`, all mutating actions enforce the approval gate:

```
Tool Invocation (e.g., nas_shares(action="create", ...))
         │
         ▼
 Is dry_run == True?
    ├── YES ──► Return Change(dry_run=True, summary="Would create...", detail=payload)
    └── NO
         │
         ▼
 Is HOMELAB_READ_ONLY == True?
    ├── YES ──► Raise HomelabError("nas", "read_only", "Refused under HOMELAB_READ_ONLY")
    └── NO
         │
         ▼
 Is HOMELAB_NAS_ALLOW_WRITES == True?
    ├── YES ──► Log "approved" ("settings") ──► Execute API Call ──► Return Change(changed=True)
    └── NO
         │
         ▼
 Does MCP Client support Elicitation?
    ├── YES ──► Prompt User: "Homelab (nas) will <action summary>. Approve?"
    │             ├── Approved ──► Log "approved" ("person") ──► Execute API Call
    │             └── Declined ──► Log "declined" ──► Return Change(changed=False, note="Declined")
    └── NO  ──► Log "refused" ──► Raise HomelabError("nas", "approval_unavailable", ...)
```

### Action Verbs and Summaries
- **`nas_shares create`**: `"create SMB/NFS share '{share_name}' pointing to '{path}'"`
- **`nas_shares update`**: `"update settings for share '{share_name}' (read_only={read_only})"`
- **`nas_shares delete`**: `"PERMANENTLY remove share '{share_name}' (data on disk is retained)"`
- **`nas_services restart`**: `"restart system service '{service}' (active client connections may drop)"`
- **`nas_services enable/disable`**: `"{action} system service '{service}' on startup"`
- **`nas_tasks run`**: `"trigger immediate run of scheduled task '{task_name}' ({task_id})"`

---

## 6. SSH Command Integration Architecture

While the UGOS Pro REST API handles core configuration and high-level health, lower-level diagnostics (SMART raw registers, NVMe wear percentage, hardware RAID/btrfs scrubs) require direct inspection.

### Security Perimeter & Safeguards
1. **No Arbitrary Command Execution:** No tool parameter can pass arbitrary shell strings.
2. **Fixed Command Allowlist:** The SSH client helper accepts only pre-defined enumeration tokens:
   - `CMD_SMART_STATUS`: `["smartctl", "-H", dev_node]`
   - `CMD_SMART_ALL`: `["smartctl", "-a", "-j", dev_node]`
   - `CMD_NVME_LOG`: `["nvme", "smart-log", dev_node, "-o", "json"]`
   - `CMD_BTRFS_USAGE`: `["btrfs", "filesystem", "usage", "-b", path]`
   - `CMD_MDSTAT`: `["cat", "/proc/mdstat"]`
3. **Strict Parameter Validation:** Device nodes must match `^/dev/(sd[a-z]|nvme[0-9]n[0-9])$`. Path parameters must strictly match `^/volume[0-9]+$`. Any violation throws `HomelabError("nas", "bad_input", ...)`.
4. **Subprocess Execution without Shell:** Invoked using `asyncio.create_subprocess_exec("ssh", *args, shell=False)`.
5. **Batch Mode & Strict Key Verification:**
   - Arguments: `["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5", "-i", key_path, "-p", str(port), f"{user}@{host}"]`
6. **Graceful Fallback:** If SSH is unconfigured, keys are absent, or connection times out, the module returns the API-derived data and sets `detail={"ssh_status": "unconfigured" | "unreachable"}` without failing the entire tool request.

---

## 7. Doctor Probe & Health Checks

Integrated directly into `homelab_infra_mcp.doctor`:

### Probe Implementation
```python
if name == "nas":
    url = (config.get("nas", "url") or "https://192.168.68.68:9443").rstrip("/")
    # Check unauthenticated reachability or token check endpoint
    verify_ssl = config.flag("nas", "verify_ssl", False)
    async with httpx.AsyncClient(verify=verify_ssl, timeout=5.0) as client:
        r = await client.get(f"{url}/ugreen/v1/verify/check")
        # Code 1010 or 200 indicates UGOS API daemon is alive and listening
        if r.status_code == 200 or (r.status_code == 401 and "token" in r.text.lower()):
            return True, f"UGOS API at {url} answered {r.status_code}"
        return False, f"UGOS API answered {r.status_code}. Check HOMELAB_NAS_URL."
```

### Remediation Hints
- Missing `HOMELAB_NAS_USER` or `HOMELAB_NAS_PASSWORD`: `"Set HOMELAB_NAS_USER and HOMELAB_NAS_PASSWORD (or HOMELAB_NAS_PASSWORD_FILE)."`
- Connection Refused: `"Could not reach NAS at {url}. Verify NAS IP, port 9443, and that the appliance is powered on."`
- Auth Error (Code 1010 / 401): `"Authentication failed. Verify credentials in UGOS Control Panel -> User Management."`

---

## 8. Test Strategy & Verification Plan

Unit testing will reside in `tests/test_nas.py` and test against mock fixtures:

1. **Configuration & Discovery Tests:**
   - Verify `NasModule` defaults to `default_enabled=False`.
   - Verify `missing()` reports absent `HOMELAB_NAS_USER` and `HOMELAB_NAS_PASSWORD`.
   - Verify `HOMELAB_NAS_PASSWORD_FILE` successfully populates password.
2. **Tool Schema & Paging Tests:**
   - Test `nas_status(action="overview")` with fixture JSON payload.
   - Test `nas_storage(action="volumes", limit=1, offset=1)` returns proper paging tuple.
   - Test `nas_shares(action="list")` returns correct items.
3. **Approval Flow & Dry Run Tests:**
   - Test `nas_shares(action="create", share_name="test", path="/volume1/test", dry_run=True)` returns `Change(dry_run=True)`.
   - Test `nas_shares(action="create")` with `HOMELAB_READ_ONLY=true` raises `HomelabError`.
   - Test `nas_shares(action="create")` with elicitation declined returns `Change(changed=False)`.
   - Test `nas_shares(action="create")` with `HOMELAB_NAS_ALLOW_WRITES=true` executes change without elicitation.
4. **SSH Execution & Fallback Tests:**
   - Mock subprocess calls to `smartctl` returning JSON output.
   - Test command injection attempts (e.g. `disk_id="sda; rm -rf /"`) are rejected by boundary validation.
   - Test timeout / connection failure falls back gracefully to API health values.
5. **Doctor Probe Tests:**
   - Test mock transport returning 200 for `/ugreen/v1/verify/check` yields healthy doctor line.

---

## 9. Alignment with Phase 1 & Dependencies

- **Precondition:** Blocked for live deployment until the 12 TB storage volume is installed and the `ugreen-nas` CMDB host is marked `active`.
- **Phase 1 Artifact:** `docs/ugos-api.md` captures exact payload structures from browser network capture.
- **Implementation Readiness:** Once this design document is approved, Phase 3 implementation will proceed directly to building `src/homelab_infra_mcp/modules/nas.py` and `tests/test_nas.py` following this exact blueprint.
