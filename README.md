# safe-codex

Run Codex in a disposable Podman or Docker container with a small, explicit host
surface.

The launcher keeps Codex state in an engine-managed volume, avoids mounting host
`~/.codex`, drops Linux capabilities, uses a read-only container filesystem, and
routes default network access through a proxy that blocks local/private
destinations.

Full documentation is published at <https://numpde.github.io/safe-codex/>.

Common commands:

```bash
./bin/safe-codex-podman doctor
./bin/safe-codex-podman build
./bin/safe-codex-podman run
./bin/safe-codex-podman run --workspace-ro --network openai --profile cautious
./bin/safe-codex-podman profiles
```

Optional host guard, for keeping host `node` and Codex available while blocking
normal `npm`, `npx`, and `corepack` use:

```bash
./bin/install-node-package-tool-deny-stubs --dry-run
./bin/install-node-package-tool-deny-stubs
```

Run checks:

```bash
./bin/check
```
