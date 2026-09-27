// Loopback HTTP bridge to the only mounted Unix socket. No external TCP egress.
import http from "node:http";
import net from "node:net";

const socketPath = process.env.BRIDGE_SOCKET || "/relay/api.sock";
const server = http.createServer((req, res) => {
  const upstream = http.request({socketPath, method: req.method, path: req.url,
    headers: req.headers}, reply => {
    res.writeHead(reply.statusCode, reply.headers);
    reply.pipe(res);
  });
  upstream.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.on("error", () => upstream.destroy());
  req.pipe(upstream);
});
if (process.env.BRIDGE_CONNECT === "1") {
  server.on("connect", (req, client, head) => {
    const upstream = net.connect(socketPath, () => {
      upstream.write(`CONNECT ${req.url} HTTP/1.1\r\nHost: ${req.url}\r\n\r\n`);
      if (head.length) upstream.write(head);
      client.pipe(upstream);
      upstream.pipe(client);
    });
    upstream.on("error", () => client.destroy());
    client.on("error", () => upstream.destroy());
    client.on("close", () => upstream.destroy());
  });
}
server.listen(Number(process.env.BRIDGE_PORT || "8000"), "127.0.0.1");
