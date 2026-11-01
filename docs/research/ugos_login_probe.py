#!/usr/bin/env python3
"""Probe: log in to the UGOS Pro API as nas-agent and make read-only calls.

Prints result codes and field names only, never the password or the token.
Password is read from /Volumes/data/secrets/ugreen_nas_agent_password.
"""
import base64
import hashlib
import http.client
import json
import ssl
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

USER = "nas-agent"
PW = open("/Volumes/data/secrets/ugreen_nas_agent_password").read().strip()
HOST, PORT = "192.168.68.68", 9443
# The NAS uses a self-signed certificate, so trust is by PIN: every connection's
# certificate must match this SHA-256 fingerprint BEFORE any request (and so any
# credential) is sent. A mismatch aborts. (Security review 2026-11-01.)
PIN = "30A0C168DC1B8169927A712F8B7214F7B2476DB7C8660C066DDBC92EF541683A"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # chain check replaced by the exact-fingerprint pin below


def call(method, path, body=None, headers=None):
    conn = http.client.HTTPSConnection(HOST, PORT, context=CTX, timeout=15)
    conn.connect()
    fp = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().upper()
    if fp != PIN:
        conn.close()
        sys.exit(f"certificate pin mismatch: refusing to send anything (got {fp[:16]}...)")
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                 headers={"Content-Type": "application/json", **(headers or {})})
    r = conn.getresponse()
    out = (dict(r.getheaders()), json.loads(r.read() or b"{}"))
    conn.close()
    return out


hdrs, _ = call("POST", "/ugreen/v1/verify/check", {"username": USER})
pem = base64.b64decode(hdrs.get("x-rsa-token") or hdrs.get("X-Rsa-Token"))
key = serialization.load_pem_public_key(pem)
enc = base64.b64encode(key.encrypt(PW.encode(), padding.PKCS1v15())).decode()

_, res = call("POST", "/ugreen/v1/verify/login",
              {"username": USER, "password": enc, "keepalive": True, "otp": True, "is_simple": True})
code = res.get("code")
data = res.get("data") or {}
print("login code:", code, "| msg:", res.get("msg"), "| data fields:", sorted(data.keys()))
token = data.get("token") or data.get("static_token")
if code != 200 or not token:
    sys.exit(1)

ok = 0
for path in ("/ugreen/v1/sysinfo/machine/common", "/ugreen/v1/storage/pool/list"):
    for style in ("query", "header"):
        p = f"{path}?token={token}" if style == "query" else path
        h = {"x-ugreen-token": token} if style == "header" else {}
        try:
            _, r = call("GET", p, headers=h)
        except Exception as e:  # noqa: BLE001
            print(f"{path} [{style}]: error {type(e).__name__}")
            continue
        d = r.get("data")
        print(f"{path} [{style}]: code {r.get('code')} | data fields: {sorted(d.keys())[:8] if isinstance(d, dict) else type(d).__name__}")
        if r.get("code") == 200:
            ok += 1
            break
sys.exit(0 if ok == 2 else 2)
