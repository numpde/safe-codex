# Containerized local Pi experiment

Pi 0.86.1 runs here; the pinned Minima Qwen3.8/vLLM server lives in
`~/repos/proart-llm/vllm`. This is an experimental, offline coding sandbox.
It initially copies committed `HEAD`, saves workspace and session snapshots,
and does not apply changes to your checkout.

## Build and run

Pi is an agent mode of the main `safe-codex` launcher. For an interactive
terminal session with the already-built image:

```bash
bash ~/repos/proart-llm/vllm/start.sh
~/repos/safe-codex/bin/safe-codex --engine docker pi --workspace ~/repos/proart-llm
# Resume the last Pi conversation in that workspace/profile:
~/repos/safe-codex/bin/safe-codex --engine docker pi --workspace ~/repos/proart-llm -- -c
# Native Pi print mode:
~/repos/safe-codex/bin/safe-codex --engine docker pi --workspace ~/repos/proart-llm -- -p 'Explain this repository.'
# Inspect the live repository and its real Git history without write access:
~/repos/safe-codex/bin/safe-codex --engine docker pi --workspace ~/repos/proart-llm --workspace-ro
```

The interface is `safe-codex --engine docker pi [options] -- [Pi arguments]`.
`bin/safe-pi` remains a compatibility alias. Type directly into Pi; use `/quit`
to exit. `-p` prints and exits;
`-c` continues the previous conversation. Native flags belong after `--`.
`--profile NAME` selects a saved sandbox (default: `default`), separately for
each workspace path. Subsequent launches restore that sandbox's files and session
history; they do not refresh from your checkout. Use a new profile to start from
the current committed `HEAD`. Home/configuration changes are not persisted.
Edits never touch your checkout. On exit the launcher saves workspace and session
tar archives under the printed output directory and removes the containers.
With `--workspace-ro`, the real repository is mounted read-only: branches,
history, ignored files and uncommitted changes are visible, editing is disabled,
and only Pi's session archive is restored. Each launch sees the host repository's
current state. Read-only and copied-workspace profiles are kept separate.
Native Pi modes have no automatic acceptance verifier
or controller-driven checkpoint/restart; the inference context limits still apply.
Their system addendum describes only the sandbox. Ledger, test, and verifier
instructions are added only by the qualification controller.
Use `--backend exl3` to connect to the manually started EXL3 server
(`../proart-llm/bin/exl3-server start`); the default `vllm` backend is unchanged.
EXL3 requires the server's `proart-exl3_inference` volume and reports a readiness
error if it is unavailable. Backend profiles are kept separate.
The default session limit is four hours (`--timeout` sets seconds). Export gets
a separate three-minute grace period; if export fails, the sandbox is retained
for recovery rather than deleting unsaved work. The vLLM backend has a 64K
context and EXL3 has a 262K context; both have a 16K per-turn output limit. No
downloads occur when launching the UI.

Requirements: Linux, Docker, host Python 3, Git, Bash, flock, UID/GID 1000,
the cached Python bootstrap image from phase one, and WLAN interface `wlp10s0`.
No host Node/npm installation is used. Start the inference server first:

```bash
bash ~/repos/proart-llm/vllm/start.sh
# Download locked dependencies through WLAN, then build without network:
bin/safe-codex --engine docker pi build --prepare
# Subsequent builds can use the prepared artifacts entirely offline:
bin/safe-codex --engine docker pi build --offline
```

For automated tasks with an independent completion gate, the separate
qualification controller accepts a task and trusted verifier:

```bash
python3 pi/controller.py --repo /path/to/repository \
  --task /path/to/task.txt --verifier /path/to/trusted-verify.py \
  --timeout 1800
```

The verifier is trusted standalone Python, mounted read-only only into a separate
container. It receives the candidate at `/workspace`; its exit status is the
completion gate. It must independently check the actual acceptance contract.
**Do not import candidate code into the trusted verifier process.** The included
duration-parser verifier tests candidate behavior through child processes and
protects its parent process against same-user memory access. Regression checks
reject early `os._exit(0)` and assertion monkeypatching. A passing verifier is only
as strong as its acceptance tests.

The image includes Python, Git, Bash, ripgrep and fd. Every build exercises all
seven Pi tools offline before recording the runnable image ID. Projects needing additional
dependencies require an explicitly prepared offline image and their own verifier.
Submodules, Git LFS payloads and uncommitted files are not copied by `git archive`.

## Permissions and network

| Component | Access |
| --- | --- |
| Pi and its tools | UID 1000, no capabilities, no-new-privileges, default seccomp, read-only root, `--network none` |
| Workspace | Disposable 512 MiB copy by default; optional explicit read-only repository bind mount |
| Session/home/temp | Bounded tmpfs: 64/32/128 MiB |
| Agent resources | 2 GiB RAM with no additional swap, 2 CPUs, 128 PIDs |
| Inference | Read-only Unix socket mount; only model listing and pinned chat completions |
| Relay | Separate non-root container on internal inference network; no workspace |
| Snapshot | Capability-free, offline helper joins paused agent PID namespace to read tmpfs; no host extraction |
| Verifier | Separate offline container, frozen candidate, read-only trusted verifier; no inference socket |
| Build downloads | Trusted short-lived processes using host networking, zero capabilities, outbound TCP bound to WLAN |

No agent GPU, Docker socket, SSH keys, credentials, browsing, package installation,
extensions, skills or project-local Pi configuration. Pi's tools are `read`,
`bash`, `edit`, `write`, `grep`, `find`, and `ls`.

WLAN binding fails closed; there is no modem fallback. Small DNS queries still
use the host resolver. The build proxy accepts TLS tunnels only to the npm and
Alpine registries and rejects private IP destinations. All package integrity
hashes and exact APK versions are locked; npm installation scripts are disabled.
The final image build uses `--network none`. Build helpers and their socket volume
are removed afterwards. Docker access belongs to the trusted host controller;
Docker and the host kernel remain part of the trust boundary.

## Reasoning and completion

The relay forces `xhigh`, preserved thinking, temperature 1, top-p .95, top-k 64,
min-p 0, and at most 16,384 output tokens. The vLLM 27B backend remains at 65,536
total tokens with a 49,152-token prompt ceiling. Flash-Next uses its native
262,144-token context with a 245,760-token hard prompt ceiling. The relay checks
the rendered prompt and logs only metadata, then removes the rendered prompt field
before returning the response. Inference remains one sequence without speculative
decoding.

Pi proactively compacts 27B sessions at the 49,152-token boundary, reserving
16,384 tokens for a response and retaining the latest 12,000 tokens. Flash-Next
compacts at about 196,608 tokens and retains the latest 32,768 tokens.
The full session remains in its JSONL history, while `.agent/STATE.md` provides a
durable task ledger in the saved workspace. If Pi's estimate misses the boundary,
the relay returns a recognized context-overflow error so Pi compacts and retries.

The qualification controller starts checkpointing at 44K reported live tokens, earlier than the
suggested 48–52K because it reserves space for a ledger update. Repeated identical
failed tools, length stops and bounded turn counts also trigger checkpoints.
It keeps at most four attempts, starts fresh sessions from the task, ledger,
diff and failure evidence when needed, and only accepts an independent verifier
pass. The entire run has a wall-clock deadline; cleanup has separate short limits.

`pi/results/<run>/` holds runtime status, isolation results, relay metadata,
and candidate/session tar archives. Qualification runs also export the diff
preview, `STATE.md`, and verifier output. `pi/state/` holds profile pointers
and locks; concurrent use of the same workspace/profile is rejected.
Archives are untrusted: inspect or unpack them only in a disposable container.
The text diff is bounded and may omit large or binary files; the archive is the
candidate artifact. Sessions contain task content and reasoning; keep them private.
Workspace and sessions survive normal checkpoints through exported artifacts,
but abrupt host/controller failure can lose changes since the last export.

## Checks

```bash
python3 pi/test-boundaries.py
python3 pi/test-launch.py
# Also exercise adversarial verifier cases and a saved real candidate:
python3 pi/test-boundaries.py --candidate pi/results/<run>/candidate-1.tar
```

Each launch runs `isolation-test.py` to check effective
capabilities, user, seccomp, read-only policy, bounded
storage, blocked external TCP and inference endpoint restrictions before Pi starts.
Use the qualification controller's `--expect-initial-failure` for an unfinished fixture to prove the
gate initially rejects it.
