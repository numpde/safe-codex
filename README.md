# safe-codex

Run Codex in a disposable Podman or Docker container with a small, explicit host
surface.

The launcher keeps Codex state in an engine-managed volume, avoids mounting host
`~/.codex`, drops Linux capabilities, uses a read-only container filesystem, and
routes default network access through a proxy that blocks local/private
destinations.

Full documentation is published at <https://numpde.github.io/safe-codex/>.

## Quick start

```bash
./bin/safe-codex-podman doctor
./bin/safe-codex-podman build
./bin/safe-codex-podman run
./bin/safe-codex-podman run --workspace-ro --network openai --profile cautious
./bin/safe-codex-podman run --gpu nvidia --profile gpu
./bin/safe-codex-podman profiles
```

GPU devices are not exposed by default. Use `--gpu nvidia` for all NVIDIA GPUs,
`--gpu nvidia:0` or `--gpu nvidia:0,1` for selected NVIDIA GPUs, or
`--gpu dri:/dev/dri/renderDNNN` for an explicit DRI render node.

## Optional host helpers

Keep host `node` and Codex available while blocking normal `npm`, `npx`, and
`corepack` use:

```bash
./bin/install-node-package-tool-deny-stubs --dry-run
./bin/install-node-package-tool-deny-stubs
```

Install native Codex without `npm`, `npx`, `corepack`, `nvm`, or `node`:

```bash
./bin/install-native-codex-cli --dry-run --version 0.130.0
./bin/install-native-codex-cli --version 0.130.0
```

To bind its downloads to a particular network interface (for example, Wi-Fi
instead of a USB modem), set `SAFE_CODEX_DOWNLOAD_INTERFACE`:

```bash
SAFE_CODEX_DOWNLOAD_INTERFACE=wlp10s0 ./bin/install-native-codex-cli --version 0.130.0
```

## Checks

The same launcher also runs the fully containerized local Pi harness:

```bash
./bin/safe-codex --engine docker pi --backend exl3 --workspace ~/repos/project
./bin/safe-codex --engine docker pi --backend exl3 \
  --workspace ~/repos/project --workspace-ro
```

Pi keeps its inference-only relay and stricter network policy. By default it
uses a disposable copy of committed `HEAD`; `--workspace-ro` exposes the real
repository and Git history without write access. See [pi/README.md](pi/README.md).

```bash
./bin/check
```
