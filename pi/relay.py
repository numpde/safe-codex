"""Inference-only Unix-socket gateway. This container never mounts the workspace."""
from http.server import BaseHTTPRequestHandler
import http.client
import json
import os
import socket
import socketserver
import threading

LIMIT = 2 * 1024 * 1024
BACKEND = os.environ.get("SAFE_PI_BACKEND", "vllm")
MODEL = "qwen3.8-flash-next" if BACKEND == "exl3" else "qwen3.8-27b"
UPSTREAM = "proart-vllm-server-1"
CONTEXT_LIMIT = 262144 if BACKEND == "exl3" else 65536
PROMPT_LIMIT = CONTEXT_LIMIT - 16384
TEMPLATE = {"enable_thinking": True, "preserve_thinking": True, "reasoning_effort": "xhigh"}
slots = threading.BoundedSemaphore(2)


def audit(**data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


class UnixHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/upstream/api.sock")


def upstream_connection(timeout):
    return UnixHTTPConnection("localhost", timeout=timeout) if BACKEND == "exl3" else http.client.HTTPConnection(UPSTREAM, 8000, timeout=timeout)


def upstream_json(path, body):
    connection = upstream_connection(120)
    try:
        connection.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        response = connection.getresponse()
        data = response.read(4 * LIMIT)
        if response.status != 200:
            raise ValueError(f"Upstream {path} returned {response.status}")
        return json.loads(data)
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reject(self, code, message):
        body = json.dumps({"error": {"message": message, "type": "policy_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/v1/models":
            return self.reject(403, "Only the inference API is available")
        body = json.dumps({"object": "list", "data": [{"id": MODEL, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.reject(403, "Only chat completions are allowed")
        if not slots.acquire(blocking=False):
            return self.reject(429, "Inference concurrency limit")
        try:
            self.forward()
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.reject(400, "Invalid inference request")
        except (OSError, http.client.HTTPException):
            audit(error="upstream_or_client_disconnected")
        finally:
            slots.release()

    def forward(self):
        self.connection.settimeout(1800)
        length = int(self.headers.get("Content-Length", "0"))
        if self.headers.get("Transfer-Encoding") or not 0 < length <= LIMIT:
            return self.reject(413, "Request size/framing rejected")
        incoming = json.loads(self.rfile.read(length))
        if not isinstance(incoming, dict):
            return self.reject(400, "Request must be an object")
        if incoming.get("model") != MODEL or not isinstance(incoming.get("messages"), list):
            return self.reject(400, "Only the pinned local model is available")
        if not all(isinstance(message, dict) for message in incoming["messages"]):
            return self.reject(400, "Messages must be objects")
        # Do not let multimodal URL/file payloads turn vLLM into a fetch proxy.
        for message in incoming["messages"]:
            if set(message) - {"role", "content", "name", "tool_calls", "tool_call_id",
                               "reasoning_content", "reasoning"}:
                return self.reject(400, "Unsupported message field")
            if message.get("role") not in ("system", "user", "assistant", "tool"):
                return self.reject(400, "Unsupported message role")
            content = message.get("content")
            if isinstance(content, list):
                if not all(isinstance(part, dict) and set(part) == {"type", "text"}
                           and part["type"] == "text" and isinstance(part["text"], str)
                           for part in content):
                    return self.reject(400, "Only text content is allowed")
            elif content is not None and not isinstance(content, str):
                return self.reject(400, "Only text content is allowed")
        allowed = {"model", "messages", "tools", "tool_choice", "stream", "stream_options",
                   "max_tokens", "max_completion_tokens", "temperature", "top_p", "top_k",
                   "min_p", "reasoning_effort", "chat_template_kwargs", "store"}
        if set(incoming) - allowed:
            return self.reject(400, "Unsupported inference option")
        maximum = incoming.get("max_tokens", incoming.get("max_completion_tokens", 16384))
        if type(maximum) is not int or not 0 < maximum <= 16384:
            return self.reject(400, "Output limit must be between 1 and 16384")
        body = {key: incoming[key] for key in
                ("messages", "tools", "tool_choice", "stream", "stream_options") if key in incoming}
        body.update(model=MODEL, temperature=1.0, top_p=0.95, top_k=64, min_p=0,
                    max_tokens=maximum, chat_template_kwargs=TEMPLATE,
                    reasoning_effort="xhigh")
        reasoning = [m.get("reasoning_content") or m.get("reasoning")
                     for m in body["messages"] if m.get("role") == "assistant"]
        reasoning = [r for r in reasoning if isinstance(r, str) and r.strip()]
        tokenized = upstream_json("/tokenize", {
            "model": MODEL, "messages": body["messages"], "tools": body.get("tools"),
            "add_generation_prompt": True, "chat_template_kwargs": TEMPLATE})
        count = tokenized["count"]
        audit(event="request", prompt_tokens=count, max_tokens=maximum,
              reasoning_messages=len(reasoning), reasoning_chars=sum(map(len, reasoning)),
              tool_results=sum(m.get("role") == "tool" for m in body["messages"]),
              thinking="xhigh", temperature=1.0, top_p=0.95, top_k=64)
        if count > PROMPT_LIMIT or count + maximum > CONTEXT_LIMIT:
            return self.reject(413, "Your input exceeds the context window of this model")
        # Inspect the real prompt in the first response, without logging its contents.
        body["return_prompt_text"] = True
        connection = upstream_connection(1800)
        try:
            connection.request("POST", "/v1/chat/completions", json.dumps(body),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Connection", "close")
            self.end_headers()
            total = 0
            for line in response:
                total += len(line)
                if total > 64 * LIMIT:
                    raise ValueError("Response too large")
                if line.startswith(b"data: {") or not body.get("stream"):
                    try:
                        value = json.loads(line[6:] if line.startswith(b"data: ") else line)
                        rendered = value.pop("prompt_text", None)
                        if rendered is not None:
                            audit(event="rendered_prompt", xhigh="Reasoning effort is set to xhigh" in rendered,
                                  preserved=all(r.strip() in rendered for r in reasoning),
                                  reasoning_messages=len(reasoning))
                            line = ((b"data: " if body.get("stream") else b"")
                                    + json.dumps(value).encode() + b"\n")
                    except (ValueError, AttributeError):
                        pass
                self.wfile.write(line)
                self.wfile.flush()
        finally:
            connection.close()
            self.close_connection = True


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    path = "/relay/api.sock"
    if os.path.exists(path):
        os.unlink(path)
    with Server(path, Handler) as server:
        os.chmod(path, 0o660)
        audit(event="ready", endpoint="unix:/relay/api.sock")
        server.serve_forever()
