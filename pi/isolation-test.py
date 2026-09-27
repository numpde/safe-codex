"""Runs as the same user and within the same container as the agent."""
import http.client
import json
import os
from pathlib import Path
import socket

assert os.getuid() == 1000 and os.getgid() == 1000
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert int(status["CapEff"].strip(), 16) == 0
assert status["NoNewPrivs"].strip() == "1"
assert status["Seccomp"].strip() == "2"
for path in ("/var/run/docker.sock", "/run/docker.sock", "/dev/nvidia0", "/home/ra/.ssh", "/checks"):
    assert not Path(path).exists(), path
for path in ("/etc/safe-pi-write-test", "/opt/safe-pi/policy/models.json"):
    try:
        descriptor = os.open(path, os.O_WRONLY | (os.O_CREAT if "write-test" in path else 0))
    except OSError:
        pass
    else:
        os.close(descriptor)
        raise AssertionError(f"Unexpected write access: {path}")
for address in (("1.1.1.1", 443), ("172.24.0.1", 22), ("192.168.8.1", 80)):
    try:
        socket.create_connection(address, timeout=0.3)
    except OSError:
        pass
    else:
        raise AssertionError(f"Unexpected TCP access: {address}")
WORKSPACE_MODE = os.environ.get("SAFE_PI_WORKSPACE_MODE", "copy")
if WORKSPACE_MODE == "copy":
    assert os.statvfs("/workspace").f_blocks * os.statvfs("/workspace").f_frsize <= 512 * 1024**2
elif WORKSPACE_MODE == "ro":
    workspace_mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) > 5 and fields[4] == "/workspace":
            workspace_mounts.append(fields[5].split(","))
    assert workspace_mounts and any("ro" in options for options in workspace_mounts), workspace_mounts
else:
    raise AssertionError(f"Unknown workspace mode: {WORKSPACE_MODE}")
assert os.statvfs("/sessions").f_blocks * os.statvfs("/sessions").f_frsize <= 64 * 1024**2
MODEL = os.environ.get("SAFE_PI_MODEL", "qwen3.8-27b")
try:
    os.unlink("/relay/api.sock")
except OSError:
    pass
else:
    raise AssertionError("Agent can unlink the inference socket")


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect("/relay/api.sock")


def check(method, path, expected, body=None, headers=None):
    client = UnixHTTP("localhost", timeout=5)
    try:
        client.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        response = client.getresponse()
        assert response.status == expected, (method, path, response.status, response.read(1024))
        response.read()
    finally:
        client.close()


check("GET", "/v1/models", 200)
check("GET", "/metrics", 403)
check("POST", "/load_weights", 403, {})
check("POST", "/v1/chat/completions", 400, [])
check("POST", "/v1/chat/completions", 400, {"model": MODEL, "messages": [None]})
check("POST", "/v1/chat/completions", 400, {"model": "other", "messages": []})
check("POST", "/v1/chat/completions", 400,
      {"model": MODEL, "messages": [{"role": "user", "content": [
          {"type": "image_url", "image_url": {"url": "http://127.0.0.1/private"}}]}]})
check("POST", "/v1/chat/completions", 400,
      {"model": MODEL, "messages": [], "max_tokens": 16385})
check("POST", "/v1/chat/completions", 400,
      {"model": MODEL, "messages": [], "chat_template": "override"})
check("POST", "/v1/chat/completions", 413, headers={"Content-Length": str(2 * 1024**2 + 1)})
workspace_result = ("bounded copied workspace" if WORKSPACE_MODE == "copy"
                    else "explicit read-only host workspace")
print(f"PASS non-root, zero capabilities, no-new-privileges, seccomp, {workspace_result}; no GPU/socket mounts")
print("PASS Internet/LAN/host-bridge TCP denied; inference socket cannot be replaced")
print("PASS inference gateway rejects admin endpoints, other models, multimodal URLs, excessive output, template overrides, oversized bodies")
