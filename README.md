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

The DeepSeek lane runs DeepSeek's official developer-preview Harness (`dsh`).
Export only the credential that Harness consumes, then run a one-shot headless
task. The workspace is read-only unless you explicitly grant write access.

```bash
export DEEPSEEK_API_KEY=...
./bin/safe-deepseek-podman doctor
./bin/safe-deepseek-podman build
./bin/safe-deepseek-podman run --workspace-ro --network proxy -- \
  --profile headless "Summarize this repository"
```

Use `--workspace-rw` only for a task that should edit the checkout. Harness state
is kept in a dedicated `safe-deepseek-state-*` volume mounted at `~/.dsh`; host
`~/.dsh` is never mounted. The image installs the pinned official
`@deepseek-ai/dsh` package and removes npm, npx, and corepack from the runtime.
The pinned preview currently needs Node's `--expose-internals` startup flag when
its native loader fallback is unavailable. The image grants that flag only to
the Harness process; it is not inherited by commands the agent starts.
The Harness release is pinned, but builds still refresh the base image and
Debian packages; this lane does not claim bit-reproducible supply-chain output.

```bash
./bin/safe-deepseek-podman run --workspace-rw --network proxy -- \
  --profile headless "Implement the requested change"
```

The Web UI is intentionally not exposed by this lane. It is an unauthenticated
remote-code-execution surface that needs a separate loopback publication and
browser-trust design; this launcher publishes no ports. DeepSeek Harness is in
developer preview and may make compatibility-breaking changes. Update its pin
explicitly:

```bash
./bin/safe-deepseek-podman build --dsh-version VERSION
```

This is containment, not a hostile-code sandbox. The Harness process and its
commands can read the API key and every file mounted into the container. A
read-only workspace prevents writes, not reads; the proxy blocks private/local
destinations, not Internet exfiltration. Do not mount a checkout containing
credentials you are unwilling to disclose to the model or executed code.

Upstream: <https://github.com/deepseek-ai/deepseek-harness>

The cloud-provider Pi lane (`safe-pi`) runs the official Pi Agent Harness with a read-only workspace by
default. Its state lives only in the container's home tmpfs and disappears when
the run exits; host `~/.pi/agent`, subscription tokens, sessions, extensions,
and settings are not mounted. Export exactly one supported provider credential
before running Pi:

```bash
export ANTHROPIC_API_KEY=...
./bin/safe-pi-podman doctor
./bin/safe-pi-podman build
./bin/safe-pi-podman run --workspace-ro --network proxy
```

The admitted Pi credentials are `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, and `OPENROUTER_API_KEY`. The launcher
refuses to expose more than one at once. The image pins the official package,
disables its version check, ignores npm lifecycle scripts during installation,
and removes npm, npx, and corepack at runtime. This intentionally prevents Pi
from installing or updating extensions inside the container. The launcher also
injects `--no-approve` and rejects `--approve`/`-a`, so repository-controlled Pi
extensions and settings cannot execute with the provider credential.

```bash
./bin/safe-pi-podman run --workspace-ro --network proxy -- \
  -p "Summarize this repository"
```

Grant `--workspace-rw` only when the task should modify the checkout. Update the
pin explicitly with `safe-pi-podman build --pi-version VERSION` after reviewing
the upstream release. Upstream: <https://github.com/earendil-works/pi>

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

On Linux, the installer removes older stable payloads that it created with its
locking protocol and that are not running through the generated launcher. It
keeps newer, prerelease, and unmarked legacy payloads. Pass `--keep-old` to
retain all versions. The lock covers runs started through the launcher; direct
binary invocations and detached helpers are not protected. On macOS, automatic
cleanup is skipped.

To bind its downloads to a particular network interface (for example, Wi-Fi
instead of a USB modem), set `SAFE_CODEX_DOWNLOAD_INTERFACE`:

```bash
SAFE_CODEX_DOWNLOAD_INTERFACE=wlp10s0 ./bin/install-native-codex-cli --version 0.130.0
```

## Checks

The main launcher also runs a separate local-inference Pi harness:

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
