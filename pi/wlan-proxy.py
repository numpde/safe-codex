"""Temporary build-only CONNECT proxy; no general Internet access for Pi."""
from http.server import BaseHTTPRequestHandler
import ipaddress
import os
import select
import socket
import socketserver

ALLOWED = {"registry.npmjs.org", "dl-cdn.alpinelinux.org"}
INTERFACE = os.environ.get("WLAN_INTERFACE", "wlp10s0")
socket.if_nametoindex(INTERFACE)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        host, separator, port = self.path.rpartition(":")
        if not separator or host not in ALLOWED or port != "443":
            self.send_error(403)
            return
        upstream = None
        try:
            for family, kind, protocol, _, address in socket.getaddrinfo(
                    host, 443, socket.AF_INET, socket.SOCK_STREAM):
                if not ipaddress.ip_address(address[0]).is_global:
                    continue
                candidate = socket.socket(family, kind, protocol)
                candidate.settimeout(60)
                try:
                    candidate.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                         INTERFACE.encode() + b"\0")
                    candidate.connect(address)
                    upstream = candidate
                    break
                except OSError:
                    candidate.close()
            if upstream is None:
                self.send_error(502)
                return
            self.send_response(200, "Connection established")
            self.end_headers()
            sockets = [self.connection, upstream]
            while ready := select.select(sockets, [], [], 120)[0]:
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except OSError:
            return
        finally:
            if upstream:
                upstream.close()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


path = "/relay/build.sock"
if os.path.exists(path):
    os.unlink(path)
with Server(path, Handler) as server:
    os.chmod(path, 0o660)
    print(f"Build proxy bound to {INTERFACE}; HTTPS hosts: {sorted(ALLOWED)}", flush=True)
    server.serve_forever()
