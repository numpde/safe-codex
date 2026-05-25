# Containerized development guide

This guide is a general checklist for building development workflows where
ordinary work happens inside containers, host exposure is explicit, and each
lane has a narrow trust boundary.

The main idea is simple: do not make one powerful development container do
everything. Split work by what it needs to read, write, and reach over the
network.

The controlling question is:

```text
What authority does this lane need, and how do we prove it received no more?
```

Key terms:

- **Lane:** one supported workflow such as checks, tests, dependency install,
  build, local service, release, or interactive shell.
- **Plane:** one kind of authority the lane may receive: engine, process,
  filesystem, network, dependency update, image build, secret, device, or proof.
- **Posture:** the concrete runtime and operational settings for the lane.
- **Proof:** an automated check that the posture still matches the intended
  boundary.
- **Residual risk:** what malicious or buggy code could still do after the
  posture is applied.

## Threat model

Containers reduce ambient host exposure. They do not make arbitrary code safe.
Treat them as one layer in a local development security posture.

Important limits:

- A rootful Docker daemon gives host-root authority to users who can control it.
  On typical Linux installs, membership in the `docker` group is enough to get
  that authority.
- Rootless engines, especially rootless Podman, reduce container-engine
  authority by avoiding a routine root daemon. They still share the host kernel
  and do not make risky mounts, secrets, network, or devices safe.
- Runtime hardening does not apply to image build steps. A Dockerfile `RUN`
  instruction can still execute fetched code during the build unless the build
  path is designed for that.
- `--read-only` protects the container root filesystem, not writable bind
  mounts or writable volumes.
- `--cap-drop ALL` removes Linux capabilities; it does not block ordinary file
  writes, network connections, or protocol-level misuse.
- A non-root container user still has whatever access the bind mount and UID/GID
  mapping give it on the host.
- A digest-pinned image can still contain vulnerable or malicious software. The
  pin gives reproducibility, not trust by itself.
- Network controls are only as strong as the proxy, firewall, DNS, and runtime
  configuration actually used by the container.

The goal is least privilege with repeatable checks: each lane should get only
the host files, network, devices, secrets, and lifecycle it needs.

## Safety claim

Done well, containerization changes the failure mode from "this development
command can affect my workstation" to "this lane can affect only the files,
network destinations, secrets, devices, ports, and persistent state it was
explicitly granted."

That is a meaningful improvement for ordinary development risk: accidental
repo rewrites, install scripts, broad package-manager behavior, unintended
network calls, leaked host config, forgotten local services, and future posture
drift.

It is not a license to run arbitrary hostile code. Containers share the host
kernel. Rootful Docker is a host-level control plane. A process can still abuse
any mount, network path, secret, device, or protocol method you intentionally
grant. The guide therefore treats every lane as a bounded authority grant, not
as a magic sandbox.

## When containers are not enough

Use a stronger boundary when the code is genuinely hostile, multi-tenant, or
expected to attack the kernel/runtime boundary. Hardening flags reduce ambient
authority; they do not create a separate kernel.

Escalation options:

- A separate physical machine or disposable VM for hostile code.
- A microVM or VM-backed container runtime when workload compatibility permits.
- A syscall-interposing sandbox runtime such as gVisor when a stronger boundary
  is useful and the syscall/FS/network compatibility tradeoffs are acceptable.
- A different OS account plus rootless engine when the main concern is
  separating local development identities rather than kernel escape.

Treat stronger runtimes as their own lane posture. Document compatibility,
performance, filesystem behavior, network behavior, device support, and the
proof that the intended runtime was actually used. Do not silently fall back to
ordinary native containers when a stronger boundary was promised.

## How to read this guide

Use the language deliberately:

- **Must** means the default policy. If a lane cannot follow it, document an
  exception.
- **Should** means the recommended path. A different path is acceptable only
  when it is explicitly simpler or safer for the current project.
- **May** means an optional pattern.

If a rule cannot be checked, either turn it into a check or treat it as advice,
not policy.

## Decision standard

Optimize in this order:

1. Protect host control.
   Avoid root callers, rootful engine assumptions, host namespaces,
   privileged mode, broad devices, and container-engine sockets.

2. Protect credentials.
   Do not mount host homes, SSH material, cloud config, package-manager config,
   Docker/Podman config, agent state, or publishing credentials into routine
   lanes.

3. Protect source and outputs.
   Prefer read-only source, copied contexts, temporary manifest trees, tmpfs,
   named volumes, and narrow writable outputs over repo-root read/write mounts.

4. Protect network boundaries.
   Default to no network. When network is necessary, constrain destination,
   listener scope, protocol methods, and local/private address reachability.

5. Protect dependency state.
   Keep normal dependency commands locked. Make update mode explicit, staged,
   verified, and review-shaped.

6. Protect reproducibility.
   Pin images and tools, control build context, avoid short-name image
   resolution, and make generated artifacts drift-checked.

7. Prove the boundary.
   A posture that is not checked will drift. Prefer rendered or live checks
   whenever text inspection would miss the real behavior.

When these goals conflict, prefer a narrower lane over a clever shared one.
Adding another lane is usually cheaper than making one lane safe for several
different trust boundaries.

## Trust classes

Classify the code a lane runs before choosing its posture.

- **Repository text inspection:** linters that parse files, policy checks, and
  generated-file drift checks. Default to no network, read-only source, and a
  fixed non-root user.
- **Project execution:** unit tests, builds, docs builds, and local scripts from
  the repo. Default to no network unless required, copied context or read-only
  source, and tmpfs writes.
- **Dependency materialization:** package managers, archive downloads, and
  lifecycle-capable installers. Default to allowlisted egress, minimal
  manifests, no repo-root writes, and staged output.
- **Interactive execution:** agent shells, human dev shells, REPLs, and
  exploratory commands. Default to a rootless engine, named state, and
  read-only workspace.
- **Local service:** databases, emulators, preview servers, and local chains.
  Default to profile-gated startup, no repo mount, and loopback or internal
  ports only.
- **Release/publish:** artifact signing, registry push, and deployment. Default
  to a separate lane, release-only secrets, explicit allowlists, and immutable
  references.
- **Container management:** image builds, cache pruning, and runtime inspection.
  Default to explicit operator commands that are never hidden inside routine
  check/test lanes.

Lower trust does not always mean malicious source code. It often means the lane
runs code with a large dynamic surface: dependency scripts, generated tools,
unreviewed plugins, interactive commands, release uploaders, or protocol
clients that can change behavior through configuration. Give those lanes less
ambient authority, not more.

## Proof ladder

Match the proof to the claim. Stronger claims need stronger evidence.

1. **Source-text proof:** checks inspect checked-in Dockerfiles, Compose files,
   launchers, manifests, and docs. Use this for simple static rules such as
   "no privileged mode appears in this Compose file."

2. **Generated-artifact proof:** checks regenerate or inspect launch commands,
   install manifests, generated Dockerfiles, release metadata, or docs snippets.
   Use this when users run generated output rather than handwritten source.

3. **Rendered-runtime proof:** checks inspect `docker compose config`,
   equivalent Podman output, or the exact resolved command after env/profile
   interpolation. Use this for profiles, ports, mounts, users, networks,
   secrets, and engine-specific flags.

4. **Live allow/deny proof:** checks run a real service or proxy and show one
   expected success and one expected failure. Use this for egress filters,
   protocol allowlists, listener scope, and local/private address blocking.

5. **Clean-tree proof:** checks run from a clean checkout or copied build
   context. Use this for package/release behavior that must not depend on
   ignored files, local caches, host tools, or uncommitted state.

6. **Operational proof:** `doctor`, `status`, `profiles`, `volumes`, and
   teardown commands show what is currently running, persisted, exposed, and
   removable. Use this for interactive sessions and long-running services.

Use the lowest proof that genuinely catches the failure mode. Do not use a
string check for a bug that appears only after rendering, interpolation,
generation, or runtime behavior.

## Protection planes

Containerized development is not one wall. It is a set of protection planes.
Each plane answers one question:

```text
If this code is wrong or malicious, what can it read, write, reach, persist,
start, or publish?
```

The guide is effective when those answers stay small and reviewable. If a lane
must widen one plane, the other planes should stay narrow.

Use this quick map before reading the details:

- **Engine and host:** prefer rootless engines, especially rootless Podman for
  lower-trust local lanes, and refuse root callers for host writes. This helps
  prevent a routine lane from becoming host-root control. It does not prove
  kernel or runtime escape is impossible.
- **Runtime identity:** use non-root users, no capabilities, no new privileges,
  and resource bounds. This helps prevent broad process privilege and accidental
  root-owned output. It does not prove the process cannot misuse allowed files
  or network.
- **Filesystem:** use read-only source, copied context, and narrow writable
  outputs. This helps prevent host-home reads, repo rewrites, and arbitrary
  artifact writes. It does not prove readable source is safe to disclose.
- **Network:** default to no network or explicit proxied egress. This helps
  prevent exfiltration, local/LAN/metadata access, and accidental public
  listeners. It does not prove a networked process cannot leak readable data.
- **Dependency/update:** use locked defaults, explicit update mode, and a
  stage/apply split. This helps prevent silent lock drift and networked repo
  writes. It does not prove the locked dependency is benign.
- **Image/build:** use fully qualified digest-pinned bases, clean contexts, and
  small final images. This helps prevent surprise image drift, short-name image
  confusion, and accidental secret inclusion. It does not prove the pinned image
  has no vulnerabilities.
- **Secrets:** avoid host config mounts and scope secrets to one lane. This
  helps prevent routine tool access to high-value credentials. It does not
  prove a process given a secret will not leak it.
- **Devices:** expose no devices by default. This helps prevent accidental
  driver and device exposure. It does not prove device drivers or hardware paths
  are safe.
- **Proofs:** use offline, rendered, and live checks where appropriate. This
  helps prevent future config drift and shallow review. It does not prove
  untested behavior is safe.

### Engine and host authority

**What it helps with:** rootless engines reduce the authority of the container
runtime itself. Rootless Podman is a strong default for local development
because routine containers do not depend on a long-running root daemon. Refusing
root host execution avoids creating root-owned artifacts and avoids normalizing
high-privilege local workflows.

**Residual risk:** Docker is still a powerful local control plane. A rootful
Docker daemon, or a user who can control that daemon, can usually get
host-root. Containers also share the host kernel, so a kernel or runtime escape
is outside what Compose hardening can fully solve.

**Design consequence:** prefer rootless Podman for interactive, agent, and
lower-trust local lanes. Keep Docker support where compatibility matters, but
document that rootful Docker has a different host-authority profile. Never
mount container-engine sockets into routine lanes, and treat Docker group
membership as high-privilege host access.

### Runtime identity and capability

**What it helps with:** non-root users, dropped Linux capabilities,
`no-new-privileges`, no host namespaces, PID limits, memory limits, and
read-only root filesystems remove broad ambient process authority. Many simple
container breakout, privilege escalation, daemon-management, and host-mutation
paths stop here.

**Residual risk:** a non-root process can still read and write whatever its
mounts, secrets, network, and UID/GID mapping allow. Capability dropping does
not stop normal file I/O, normal network connections, protocol misuse, or bugs
in the application itself.

**Design consequence:** runtime hardening is the baseline, not the whole
sandbox. Combine it with narrow mounts, network policy, and secret policy.

### Filesystem and source boundary

**What it helps with:** read-only mounts, copied build contexts, temporary
manifest trees, tmpfs caches, and narrow writable outputs decide what code can
observe or alter. This is the plane that keeps package scripts from reading
host homes, keeps tests from rewriting the repository, and keeps generated
artifacts from overwriting arbitrary paths.

**Residual risk:** a writable bind mount is real host write access. A read-only
repo mount still leaks source code and any readable files inside that tree.
Named volumes persist state and can retain credentials, caches, generated code,
or poisoned tool state across runs.

**Design consequence:** avoid broad repo-root write mounts, reject symlinked or
unexpected output paths, use copied contexts for package-shaped validation, and
provide commands to list and remove persistent volumes.

### Network and egress

**What it helps with:** `network_mode: "none"`, internal networks, loopback-only
ports, and allowlisted proxies reduce exfiltration, SSRF-style local network
access, accidental public exposure, and unintended calls to package registries,
RPC endpoints, metadata services, or local daemons.

**Residual risk:** a networked process can exfiltrate anything it can read
unless egress is blocked or tightly proxied. Hostname allowlists rely on the
proxy, DNS, and runtime network configuration being correct. A localhost-bound
published port controls who can connect inbound; it does not by itself prevent
container outbound internet.

**Design consequence:** default to no network, route dependency/API lanes
through explicit proxies, block local/private/link-local destinations, and add
live allow/deny checks for important egress policy.

### Dependency and update

**What it helps with:** stage/apply lanes separate the dangerous part
downloading and executing package-manager logic from the part that writes repo
outputs. Locked default mode prevents normal install commands from silently
changing lockfiles, checksums, remappings, or generated dependency trees.

**Residual risk:** lockfiles and checksums prove identity, not goodness. A
locked malicious package remains malicious. Lifecycle scripts, arbitrary
archive URLs, Git dependencies, alternate registries, and broad generated trees
can still be dangerous if explicitly allowed.

**Design consequence:** keep networked installers away from repo-root writes,
disable lifecycle scripts by default, verify source policy and integrity, make
updates explicit, and review update diffs as supply-chain changes.

### Image and build

**What it helps with:** fully qualified digest-pinned base images, explicit
tool versions, hash-locked requirements, small final images, and `.dockerignore`
make builds reproducible and reduce accidental inclusion of local secrets,
caches, and generated artifacts.

**Residual risk:** image build steps execute code before runtime hardening
applies. A digest-pinned image can be reproducibly vulnerable. Build arguments,
logs, layers, and cache metadata can leak secrets.

**Design consequence:** treat image builds as a separate trust boundary, keep
build contexts clean, avoid build-time secrets, remove package managers from
runtime stages when not needed, and review declared pins, lock state, and built
image contents separately.

### Secrets and credentials

**What it helps with:** not mounting host homes, SSH directories, cloud config,
Docker config, package-manager config, or agent config prevents routine tools
from reading high-value credentials. Secret files and env vars scoped to one
lane reduce accidental spread.

**Residual risk:** any secret given to a container is available to that process.
Environment variables can appear in process metadata, logs, crash reports, or
debug output. Protocol/tool arguments may be visible to local hosts,
transcripts, or developer tooling.

**Design consequence:** pass secrets only to lanes that need them, prefer
read-only seed files or runtime secret mechanisms where appropriate, never bake
secrets into images, and keep publishing credentials out of normal check/test
lanes.

### Device and hardware

**What it helps with:** denying devices by default prevents accidental access to
GPUs, render nodes, USB devices, disks, KVM, container runtimes, and other host
interfaces. Explicit selectors make hardware exposure reviewable.

**Residual risk:** devices are host capabilities. A GPU, render node, or other
device may expose driver attack surface or access to data processed by that
device. Device access often needs extra groups that widen host-facing authority.

**Design consequence:** expose one concrete device or selector at a time,
validate it, avoid mounting `/dev`, and avoid combining device access with
secrets or broad writable mounts unless documented as an exception.

### Checks and proofs

**What it helps with:** repository checks, rendered Compose checks, generated
manifest drift checks, and live allow/deny checks make the intended posture
durable. They catch future edits that accidentally add network, writable mounts,
host ports, unpinned images, lock drift, or unsupported package managers.

**Residual risk:** checks can be too shallow. String checks can miss rendered
profile behavior, variable interpolation, generated launch commands, wrapper
scripts, and runtime-only failures.

**Design consequence:** test the rendered or generated artifact whenever the
bug would appear after rendering. Include self-check fixtures for policy
classifiers so reviewers know the test can fail for the right reason.

### Example: compromised dependency installer

Suppose a package installer runs malicious code.

Without these planes, it might read host SSH keys, inspect cloud credentials,
modify source files, rewrite lockfiles, open a reverse connection, poison
local caches, or leave root-owned artifacts behind.

With the guide's dependency-lane pattern:

- The source boundary gives it only manifest inputs, not the whole repository.
- The filesystem plane lets it write only to a staging volume.
- The network plane limits where it can connect.
- The update plane prevents lock and checksum changes unless update mode is
  explicit.
- The apply plane is offline and writes only expected output paths.
- The verification plane checks source policy, archive integrity, patches, and
  final installed contents before build/test consumes them.

Residual risk remains: the locked dependency can still be malicious in the code
that build/test later consumes. The pattern does not certify package quality; it
limits what the installer can do during installation and makes dependency
changes reviewable.

### How planes compose

Avoid asking only whether a workflow is "containerized". Ask narrower
questions:

- If it can write the repository, is it offline?
- If it can use the network, can it write only to a staging area?
- If it receives secrets, is network and filesystem authority as small as
  possible?
- If it publishes a port, is the listener bound to the intended interface?
- If it uses a device, are secrets and broad writable mounts absent?
- If it can update dependency metadata, is update mode explicit and reviewable?

One strong plane cannot compensate for every weak plane. A read-only root
filesystem does not help if a networked package manager has a read/write
repo-root bind mount. A digest-pinned image does not help if secrets are mounted
from the host home. A localhost-bound service does not help if the service also
has outbound internet and credentials. The goal is to make every granted
authority intentional, small, and covered by proof.

## Core rules

1. Use one supported entrypoint.
   Prefer `make` or one small launcher script over scattered shell snippets.
   Operators should be able to run `make help` or `tool doctor` and see the
   supported lanes.

2. Give every lane a declared posture.
   Document whether it has network, what it mounts, what it can write, whether
   it publishes ports, whether it needs secrets, and whether it is expected to
   be long-running.

3. Keep default lanes offline and write-free.
   Formatting, source checks, unit tests, static policy checks, and ordinary
   builds must start with no network and no write access to the source tree.
   Add exceptions lane by lane.

4. Split network from repository writes.
   A dependency tool that talks to the internet should not also receive
   repo-root read/write access. Stage into a container volume, verify, then
   apply offline to a narrow output path.

5. Make updates explicit.
   Default dependency commands must install the locked state only. Lockfile,
   checksum, generated manifest, and remapping updates should require an
   explicit flag such as `ALLOW_UPDATE=1`.

6. Prefer proof over convention.
   Add checks that render Compose files, inspect generated commands, verify
   hardening flags, and exercise expected allow/deny behavior where practical.

7. Fail closed on missing safety prerequisites.
   If rootless mode, user namespace mapping, proxy policy, read-only mounts,
   digest-pinned images, secret validation, or output-path validation is part of
   the lane's promised posture, absence of that prerequisite should stop the
   command or require an explicit weaker profile. Silent fallback is a security
   regression.

## Minimum architecture

A new containerized development setup should start with this shape:

```text
Makefile or launcher
.dockerignore
compose/
  checks.yml
containers/
  checks/Dockerfile
tests/checks/
  test_container_posture.*
```

The first lane should be `checks`: offline, read-only, non-root, no
capabilities, no container-engine socket, bounded resources, and no host
package-manager dependency. Add heavier lanes only after this guardrail exists.

The minimum supported commands are:

```text
make help
make checks
make test
make ci
```

Projects that do not use `make` should still provide the same concepts through
one documented launcher: help, checks, test, CI-equivalent, doctor/status where
long-lived state exists.

## Design sequence

Design each lane in this order:

1. Define the purpose.
   State the smallest useful outcome: check source text, run tests, install
   dependencies, build artifacts, serve local docs, run an interactive session.

2. Define owned outputs.
   List every host path the lane may create, delete, or modify. If the answer is
   "the repo", the lane is too broad.

3. Define input authority.
   Decide whether the lane needs a read-only source mount, copied build context,
   specific manifest files, a named volume, or a secret file.

4. Define network authority.
   Choose none, internal-only, allowlisted egress, ordinary internet, host
   loopback, or public inbound access. Pick the narrowest option that works.

5. Define user and resources.
   Choose fixed non-root, caller UID/GID, or a documented exception. Add CPU,
   memory, PID, and tmpfs limits.

6. Define proof.
   Add the repository check, rendered-config check, or live allow/deny check
   that would catch an accidental broadening of the lane.

7. Define residual risk.
   State what remains possible if the code in the lane is malicious. This keeps
   the review honest: every lane should say what its protections do not cover.
   Good residual-risk statements are specific:

   - "This stage can still exfiltrate the manifest files it receives to the
     allowed registry host."
   - "This offline apply lane can still overwrite the declared dependency
     output path if the staged tree passes verification."
   - "This interactive edit profile can modify the mounted workspace by design,
     but it cannot reach the network under the default profile."

   Weak statements such as "low risk" or "containerized" are not enough.

## Lane model

Use separate lanes when the trust boundary changes.

| Lane type | Network | Source access | Writes | Typical use |
| --- | --- | --- | --- | --- |
| Source checks | None | Read-only bind mount | None | Text policy, generated-file drift, Compose posture |
| Runtime checks | Local container runtime only | Read-only bind mount | None | Rendered Compose checks, local service posture checks |
| Live checks | External network, explicit | Read-only inputs | None | Prove proxy allow/deny behavior or upstream reachability |
| Tests | Usually none | Copied build context or read-only mount | Tmpfs only | Unit, integration, invariant, parity tests |
| Package/build | Usually none after image build | Copied build context | Narrow artifact output | Wheels, sdists, release-shaped artifacts |
| Dependency stage | Allowlisted egress only | Minimal input files | Container volume | Package manager install, archive download |
| Dependency apply | None | Staged output plus narrow repo outputs | Narrow repo outputs | `node_modules`, `dependencies`, lock/checksum files |
| Local service | Internal network or localhost port | Usually none or read-only | Named volume or tmpfs | Databases, local chains, preview servers |
| Interactive agent/dev shell | Policy-dependent | Chosen workspace mount | Chosen workspace mount and named state | Human or agent sessions |

Do not merge lanes just because they use the same image. Merge only when the
filesystem, network, secret, port, and lifecycle posture are the same.

## Source boundary choices

Choose the source boundary intentionally:

| Boundary | Use for | Do not use for |
| --- | --- | --- |
| Read-only repo mount | Source text checks, rendered config checks, docs source builds | Package-shaped validation that should ignore host artifacts |
| Copied build context | Tests that should resemble release/package behavior | Lanes that must inspect uncommitted ignored files |
| Temporary manifest tree | Networked package-manager install stages | General source checks or broad tool execution |
| Narrow writable bind | Owned generated output such as `dist/` or docs build output | Dependency tools with network access |
| Named volume | Persistent tool state, staged dependency output | Source of truth that reviewers must diff |
| Tmpfs | Caches, temporary output, build intermediates | Durable state or committed artifacts |

The default is not "mount the repository". The default is the smallest boundary
that lets the lane do its job.

## Default runtime posture

For short-lived check/test/build containers, this is the baseline
Docker/Podman-compatible CLI posture:

```text
--init
--read-only
--security-opt=no-new-privileges:true
--cap-drop ALL
--network none
--pids-limit <small bound>
--memory <small bound>
--cpus <small bound>
--tmpfs /tmp:rw,nosuid,nodev,noexec,size=<bound>
--user <non-root uid>:<non-root gid>
```

Remove or weaken these defaults only for a specific reason:

- Use executable tmpfs only when a build tool genuinely needs to execute files
  from that path.
- Add a writable bind mount only for an output the lane owns.
- Add network only for a lane whose purpose needs network.
- Add devices only behind an explicit GPU/device mode.
- Publish ports only for explicit local-service lanes, and bind host ports to
  `127.0.0.1` unless external access is the point.
- Keep the runtime's default seccomp/AppArmor/SELinux confinement unless the
  lane has a documented exception or a stricter custom profile.
- Do not use `seccomp=unconfined`, `apparmor=unconfined`, or `label=disable` as
  a routine compatibility fix.
- Make CPU, memory, PID, and tmpfs limits configurable, but keep bounded
  defaults. Resource failures should be visible rather than silently falling
  back to an unbounded run.

For Compose services, encode the same posture in YAML:

```yaml
init: true
user: "65532:65532"
network_mode: "none"
read_only: true
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
pids_limit: 128
mem_limit: 512m
tmpfs:
  - /tmp:rw,nosuid,nodev,noexec,size=64m
```

Add the same posture to generated launch manifests and user-facing run
commands. Generated commands are part of the security boundary; check them like
source code.

For rootless Podman, choose user namespace mode deliberately:

- Use `--userns=auto` for lanes that do not need host-owned writes. This keeps
  the container user further away from the caller's host identity.
- Use `--userns=keep-id` only when ergonomic writable bind mounts matter. It
  makes file ownership easier, but the process then has the caller's normal
  authority over that writable mount.
- Do not treat `keep-id` as a security boundary. It is an ownership convenience.
- `--userns=auto` depends on usable subordinate UID/GID ranges. If it is not
  available, fail with a clear diagnostic or fall back to a documented posture;
  do not silently switch to host-identity writable mounts.
- User namespace mode affects volume and bind-mount ownership. Test the actual
  generated command for each profile that writes files.
- Avoid `--network host`; it removes an important network boundary.

## Host user, engine, and root

Run routine lanes as a non-root host user. Fail fast if the caller is root or
if `LOCAL_UID=0` is supplied.

Use a fixed unprivileged user such as `65532:65532` for read-only inspection
lanes. Use the caller UID/GID only when a lane must write host-owned artifacts.

Be explicit about the engine policy:

- Prefer rootless Podman for interactive, agent, dependency-experiment, and
  lower-trust local lanes.
- Keep Docker support as a compatibility path when the project needs it.
- Check that Podman is actually rootless before presenting it as the safer
  engine path.
- Rootless Podman with `keep-id` style user mapping can make bind-mount
  ownership more ergonomic, but it does not make risky mounts safe.
- Rootless Podman with `auto` user mapping is usually better for lanes that do
  not need host writes.
- Docker with membership in the `docker` group is root-equivalent on the host.
- Rootless Docker improves that posture, but still needs separate review for
  mounts, sockets, devices, and network.
- A rootless Podman socket is less powerful than a rootful Docker socket, but
  it is still broad authority over the user's containers, images, volumes, and
  generated state. Do not mount it into routine lanes.
- Do not expose container-engine APIs over unauthenticated TCP or broad local
  networks. If a remote engine is necessary, use SSH or mutually authenticated
  TLS, scope credentials tightly, and treat client certificates or SSH keys as
  high-privilege engine credentials.

If a project supports both Docker and Podman, treat engine selection as part of
the security boundary:

- Generate or document the run arguments for each supported engine.
- Keep the common posture the same, but allow engine-specific flags where they
  improve isolation.
- Do not assume a `docker` alias to `podman`, or a Compose wrapper, has exactly
  the same mount, network, user namespace, or volume behavior.
- A `doctor` command should print the selected engine, version, rootless status,
  user namespace mode, workspace mount mode, network mode, and persistent volume
  names.
- If the promised engine posture is unavailable, fail closed or require an
  explicit weaker profile.

For long-running local services, consider rootless Podman plus user-level
systemd management. Quadlet can make rootless container services explicit and
restartable without hand-written service wrappers. Use it for service lifecycle,
not as a substitute for mount, network, secret, and device policy.

## Container management lanes

Some workflows legitimately control the local container runtime: image builds,
rendered Compose checks, live network proofs, cache pruning, service lifecycle,
or status commands. Treat these as operator lanes, not ordinary check/test
lanes.

Rules for container-management lanes:

- Do not mount the container-engine socket into an untrusted container.
- Prefer host-side launcher commands for runtime management.
- If a container must receive an engine socket, make that lane explicit,
  documented, and isolated from secrets, broad source mounts, and writable repo
  mounts.
- Keep commands narrow: build one declared image, render one declared Compose
  file, prune only declared cache classes, or manage one declared project.
- Print the selected engine, project name, profiles, networks, volumes, and
  images before mutating state.
- Do not hide container management inside `checks`, `test`, or dependency
  install unless the target name and docs make that authority obvious.
- Add checks for generated engine commands; a wrapper script is part of the
  boundary.

## Mounts and state

Treat host mounts as capabilities.

Prefer these patterns:

- Read-only source mount for source inspection.
- Copied build context for build and package lanes.
- Named volume for durable tool state.
- Tmpfs for caches and transient build output.
- Narrow read-write bind mount for owned generated artifacts.

Avoid these by default:

- Host home directories.
- `~/.ssh`, `~/.config`, `~/.docker`, cloud CLI config, package-manager config,
  token files, key files, and shell history.
- `/run`, `/var/run`, `/dev`, `/proc`, `/sys`.
- Container-engine socket mounts, including Docker and Podman sockets.
- Broad repo-root read/write mounts for networked tools.
- Symlinked output directories.

For any writable output path, check before mounting:

- The path exists when implicit host-path creation would be dangerous.
- The path is the expected file or directory type.
- The path is not a symlink.
- The resolved path remains inside the physical repository root.
- The container can write only the files or directories that lane owns.

For interactive agents, keep the agent home/state in a named volume rather than
mounting the host agent config directory. Mount the workspace read-only by
default for inspection sessions, then opt into read/write for editing sessions.
With Podman, use profile-scoped named volumes for this state so different
sessions do not silently share tool homes, caches, or credentials.

Remember that named volumes are persistent state. They are less exposed than
host home mounts, but they can still retain credentials, generated code, caches,
and poisoned tool state. Provide a way to list, inspect, and remove them by
profile or purpose.

Do not rely on engine-private volume paths as a stable interface. Use the
container engine to list, inspect, back up, or remove volumes. Rootless Podman,
rootful Docker, rootless Docker, and desktop runtimes store volume data in
different places and may apply different ownership and labeling rules.

On SELinux-enabled hosts, bind mounts need explicit labeling. Prefer private
labels for project-specific mounts and shared labels only when multiple
containers intentionally need the same content. Treat label broadening like any
other mount exception.

## Devices and GPUs

Expose no host devices by default.

When device access is necessary:

- Put it behind an explicit flag, profile, or Make target.
- Prefer a single concrete device path or GPU selector over broad device
  mounts.
- Validate the selector before invoking the container engine.
- Add only the group access required for that device.
- Do not mount `/dev` wholesale.
- Keep device-enabled lanes free of secrets and broad writable mounts unless
  the combination is explicitly justified.
- Document whether the device lane is expected to work under Docker, rootless
  Docker, rootless Podman, or only a specific host setup.

## Network policy

Use `network_mode: "none"` for anything that does not need network.

When a lane needs network, decide which of these it needs:

- No inbound ports, ordinary outbound internet.
- Outbound only to a specific API origin.
- Outbound only to public/global IP destinations.
- Outbound only to a package registry or artifact host.
- Internal container-to-container traffic only.
- Host loopback port for manual local tools.

For dependency and external API lanes, prefer a proxy or firewall boundary:

- The worker container joins only an internal network.
- The proxy is the only service with external egress.
- The proxy allowlists hostnames and port `443`.
- The proxy rejects local, private, link-local, multicast, and metadata
  addresses.
- For JSON-RPC or similar protocols, the proxy also allowlists methods rather
  than forwarding arbitrary request bodies.

Do not treat "read-only client command" as a security boundary. Enforce
read-only behavior at the proxy or server when a write-capable protocol is in
scope.

Add a live check for critical network policy:

- One expected allowed target succeeds.
- One known disallowed target fails.
- The check uses the real proxy/service definition, not a duplicated test-only
  proxy.
- Live checks are separate from offline checks so CI can choose deliberately.

For host-local services, distinguish listener scope from container egress. A
service can bind `127.0.0.1` on the host and still have outbound internet from
its bridge network. If that tradeoff is accepted, keep the service free of
secrets and broad mounts.

With rootless Podman, networking may be implemented differently from rootful
Docker. That changes ergonomics and sometimes reachability, but not the
security question. Still prove the actual listener address, the actual egress
path, and the local/private-destination blocking behavior for the command or
service definition users run.

## Dependency lanes

Dependency installation is the highest-risk ordinary development action. Use a
stage/apply design.

Build-time dependency installation is part of this risk. If an image build runs
`pip install`, `npm install`, `cargo fetch`, `apt-get`, `apk add`, or an
ecosystem-specific installer, decide whether that build is a trusted base-image
construction step or a dependency lane that needs the same source, network, and
lock policy as runtime installation.

Keep dependency images narrow. If the package installer needs one toolchain and
the verifier or patcher needs another, split them:

- Installer image: only the ecosystem tool needed to materialize the dependency
  tree.
- Verifier image: only the parser, checksum, archive, and patch tools needed to
  validate and adjust staged output.
- Apply image: only the tools needed to copy staged output into the expected
  host paths.

This prevents a staging image from accumulating Python, Node, patch tools,
compilers, and distro packages just because one script needs them. It also
makes vulnerability review more useful: a vulnerable package in a verifier
image has a different remediation path from a vulnerable package in the
installer or runtime image.

Stage service:

- Has allowlisted egress through a proxy.
- Receives only minimal input files: manifests, locks, patches, verifier code.
- Does not mount the repository root.
- Disables lifecycle scripts where the package manager allows it.
- Uses exact versions and lockfiles.
- Downloads into a temporary work tree.
- Verifies upstream archives against lockfile checksums.
- Rejects unexpected sources, URLs, registries, or archive shapes.
- Applies declared patches with recorded pre-hash, patch-hash, and post-hash.
- Writes only to a container volume.
- Has download deadlines and per-connection timeouts where the tooling allows
  them.
- For workspace package managers, receives a temporary copied manifest tree
  rather than read-only binds of the real repository. Copy only root manifests,
  workspace manifests, and existing lockfiles needed by the install.

Apply service:

- Has no network.
- Reads staged output from the volume.
- Writes only the dependency output path and allowed metadata files.
- In locked mode, fails if metadata would change.
- In update mode, copies updated lock/checksum/remapping files deliberately.
- Stages replacement under a temporary directory before replacing the visible
  installed tree.
- Uses a small, constrained stager for broad generated directories such as
  `node_modules`. The stager should validate its exact source and destination
  paths instead of accepting arbitrary copy arguments.

Verify service:

- Has no network.
- Uses read-only mounts.
- Checks installed dependency contents before build or test lanes consume them.
- Rejects missing entries, unexpected entries, checksum drift, stale metadata,
  unsafe paths, duplicate lock entries, and source-policy drift.

Update mode should be review-shaped. A successful update should leave a small,
reviewable diff in lockfiles, checksums, generated metadata, and dependency
source policy. If an update changes broad generated trees, add a summary or
manifest that reviewers can inspect without reading every file.

Before any apply service mounts a writable output path, the host entrypoint
should reject unsafe targets: symlinks, wrong file types, missing required
parents, and paths that resolve outside the intended tree. Re-run those checks
after the networked stage and immediately before the offline apply step. This
guards against container-runtime bind behavior and local races around generated
targets.

For npm-like tools:

- Use `npm ci` or equivalent in locked mode.
- Set ignore-scripts in environment, not only as command-line habit.
- Disable audit, fund, update notifier, and cache paths unless explicitly
  needed.
- Keep install policy in the container lane, not in a checked-in `.npmrc`,
  unless the repository deliberately treats `.npmrc` as a reviewed source file.
- Use one root lock source unless the dependency lane is deliberately designed
  for multiple locks.
- Reject alternate package managers and nested lockfiles unless they have their
  own lane.
- Require exact versions for external packages. Use workspace protocol entries
  only for local workspace packages.
- Check generated locks for HTTPS registry tarball sources and integrity
  metadata. Reject Git URLs, file URLs, arbitrary tarballs, alternate registries,
  and lock entries without integrity unless the lane is explicitly redesigned.

## Images and build context

Pin what matters:

- Base images by fully qualified registry name and digest.
- Tool versions in Dockerfiles.
- Package lockfiles or hash-locked requirements.
- Release scanner images and other security tooling by fully qualified registry
  name and digest.

Use a maintained base family that is compatible with the project, and pin the
exact image digest once selected. Revisit that policy on a schedule; digest
pins prevent surprise drift, including security fixes.

Avoid unqualified image names such as `node:...`, `alpine:...`, or
`hello-world` in checked-in workflows. Use explicit registry-qualified
references such as `docker.io/library/...` or the project's intended registry.
This avoids short-name resolution, registry search order, and alias behavior
that can differ between Docker, Podman, CI, and developer machines.

Choose pull behavior deliberately:

- Build/update lanes may pull when they are explicitly refreshing images.
- Routine offline checks should not implicitly pull images from the network.
- A `doctor` or status command should show the resolved image reference and
  whether the image is present locally.
- Release lanes should verify that pushed or consumed digests match the
  expected immutable reference.

When a publisher provides image signatures, attestations, provenance, or SBOMs,
verify them in an explicit image-update or release lane. Prefer modern
signature/provenance tooling such as Sigstore/Cosign or Notation over legacy
Docker Content Trust for new designs. Signature verification proves publisher
and integrity claims; it does not prove the image is vulnerability-free or
appropriate for the lane.

Provenance checks should compare the attested claims to expectations: builder
identity, source repository or revision, build type, materials or resolved
dependencies, build parameters, platform, and produced digest. An attestation
that is signed but not policy-checked is mostly inventory, not enforcement.

Use `.dockerignore` aggressively:

- Exclude `.git`, local agent/editor state, virtualenvs, build outputs, caches,
  compiled artifacts, package outputs, temp directories, and coverage output.
- Exclude common secret paths and filenames: `.env`, `.netrc`, `.npmrc`,
  `.pypirc`, `.ssh`, cloud config, Docker config, key/cert/token files.
- Keep lockfiles and source-of-truth build manifests inside the build context.

Choose build-time network deliberately:

- Use no build network for stages that should be hermetic or package-shaped.
- Treat any build stage that runs package managers, downloads archives, clones
  repositories, or contacts private services as a dependency or secret lane.
- Do not hide dependency updates inside image builds unless the build itself is
  the documented dependency-update lane.
- Make build network mode visible in the launcher, generated command, or CI
  job.

Prefer `COPY` over `ADD` unless the archive-extraction behavior is explicitly
needed. Do not use remote URL `ADD` as a dependency-download mechanism; route
remote artifacts through the same source-policy, checksum, and egress controls
as other dependencies.

Do not pass secrets through Docker build arguments. Build args are easy to leak
through image history, build logs, and cache metadata. If a build truly needs a
secret, use BuildKit secret mounts and keep the build output independent of the
secret value.

Build secret mounts and SSH mounts are better than build args or environment
variables because they are scoped to the build instruction rather than baked
into the final image. They are not magic: the build step that receives the
secret can still read or exfiltrate it. Treat secret-using builds as networked
secret lanes and keep their context, logs, network, and outputs narrow.

Build cache mounts are persistent builder state. They can improve performance,
but they can also retain downloaded packages, poisoned tool caches, or material
that should not become part of another lane. Scope cache IDs by project and
purpose, never store secrets in cache mounts, and provide a cache-prune path.

Prefer copied build context for package-shaped validation. It prevents host
`.venv`, `target`, `dist`, local extensions, and caches from leaking into the
container runtime.

Keep generated Dockerfiles or manifests under a drift check:

- One source-of-truth generator or artifact list.
- A no-write `check` target that fails when generated output is stale.
- A separate `generate` target that refreshes the checked-in file.

When runtime images do not need package managers, remove them from the final
stage. This is especially useful for npm, pip, compiler toolchains, and release
or scanner CLIs used only during build.

## Vulnerability reviews

Separate three different review questions:

- Declared pins: direct package versions, compiler versions, image tags, and OS
  package pins.
- Lock state: transitive dependency versions, registry sources, archive hashes,
  integrity fields, and generated metadata.
- Built image contents: full OS package set, language packages, copied runtime
  files, and final image configuration.

Do not treat a direct-pin advisory check as a full image scan. A targeted review
can still be valuable: it may show that a vulnerable OS package is present only
because a dependency-stage image is doing verifier work that belongs in a
smaller verifier image. Record that kind of finding as a design fix, not only as
"upgrade package X".

Prefer review notes that state:

- Date and scope.
- Data sources used.
- What was not checked.
- Direct package results.
- Lockfile or transitive dependency gaps.
- Container/image findings.
- Implemented mitigation or follow-up lane.

Scan the built image when the lane produces a runtime image, but treat scanner
output as one signal. Also inspect final image configuration: user, entrypoint,
environment, labels, exposed ports, healthcheck, working directory, copied
files, package managers, and runtime dependencies. A clean vulnerability scan
does not prove the image posture is appropriate for the lane.

## Secrets

Use the narrowest secret path the workflow supports.

Prefer:

- Runtime environment variables for short-lived non-persistent local use.
- Container/Compose secrets or read-only seed-file mounts for process startup.
- Temporary files created by the entrypoint and removed by a trap.
- Strict validation of secret file contents and environment names.

Avoid:

- Baking secrets into images.
- Storing secrets in Dockerfile `ENV` or image labels.
- Passing secrets through generated docs or manifests.
- Mounting broad host config directories.
- Logging secret values or full command lines that contain them.

For agent or protocol tools, remember that the local host process may see tool
arguments and results. If a secret passed through the tool protocol would be
visible in transcripts or debug views, prefer a startup seed file or environment
source.

## Logs and diagnostics

Treat logs as persistent outputs.

- Do not log secrets, tokens, private keys, full credential-bearing command
  lines, or sensitive protocol payloads.
- Bound log growth for long-running services with engine log options, journald
  limits, or service-specific rotation.
- Prefer local logs for local development; remote log drivers are a network and
  credential boundary.
- Include logs in incident response: a hostile lane may have written secrets or
  misleading diagnostics to stdout/stderr or service logs.
- Cleanup commands should say whether logs are in scope.

## Local services and ports

Long-running local services deserve their own Compose files and Make targets.

Use profiles so a bare `docker compose up` does not accidentally start a
host-published service. Split service variants by access boundary:

- Internal-only service: no host ports, internal network.
- Host-local service: host port bound to `127.0.0.1`.
- Public preview: explicit target, explicit host, no debug posture, bounded
  resources, and a teardown command.

If a service needs a normal bridge network to publish a localhost port, state
that tradeoff and keep the service free of secrets and repo mounts.

Do not use publish-all behavior such as `docker run -P` or equivalent generated
commands. `EXPOSE` documents intended container ports, but publish-all turns
that metadata into host listeners. Enumerate every host port explicitly and
check the rendered listener address.

## Interactive sessions

Interactive shells and agent sessions are higher risk than fixed check lanes:
the process can choose new commands at runtime. Give them stricter defaults and
clear escape hatches.

Recommended posture:

- Prefer rootless Podman as the default engine when available.
- Use named profiles for persistent state.
- Store tool home/state in a named volume, not the host home directory.
- Default to a read-only workspace for inspection sessions.
- Require an explicit option for workspace read/write.
- Use Podman `--userns=auto` for read-only or volume-only sessions where
  practical.
- Use Podman `--userns=keep-id` only for explicit workspace read/write sessions
  where host file ownership matters.
- Route ordinary network through a local/private-destination-blocking proxy, or
  use `none` for offline sessions.
- Require a separate explicit option for bridge networking.
- If Podman rootless or the selected user namespace mode is unavailable, stop
  and explain the weaker alternative instead of silently changing posture.
- Reject risky mounts by default: host home, sockets, `/run`, `/var/run`,
  `/dev`, `/proc`, `/sys`, SSH material, agent config, and cloud credentials.
- Provide `doctor`, `status`, `profiles`, `attach`, `stop`, and remove/reset
  commands so state is understandable and recoverable.

## Operator interface

Expose commands by purpose and cost.

Recommended targets:

```text
make help
make checks
make check-runtime
make check-live
make deps
make deps ALLOW_UPDATE=1
make deps-verify
make package-deps
make package-deps ALLOW_UPDATE=1
make build
make test
make package
make ci
```

Keep naming consistent:

- `checks`: offline repository/source checks.
- `check-runtime`: local container-runtime checks that avoid external network.
- `check-live`: checks that intentionally use external network.
- `deps`: install locked dependencies.
- `deps-verify`: verify installed dependencies without network.
- `package-deps`, `python-deps`, or similar names: install one specific
  dependency ecosystem when one umbrella `deps` target would hide different
  trust boundaries.
- `package`: produce local release-shaped artifacts but do not publish.
- `ci`: ordinary required gates, not slow or live checks unless intended.

Print status lines for operations that mutate local state, prune artifacts, or
install timers/services. Operators should see what is in scope and what is
deliberately not being removed or changed.

Use explicit project, profile, and volume names. Accidental reuse of a default
Compose project name can mix unrelated services, orphan cleanup, networks, and
volumes. Names should identify the lane and, for persistent state, the profile.

Validate user-provided ports, profile names, device selectors, mount
destinations, and env-file keys before passing them to the container engine.

## Source of truth

Keep the container contract in as few places as possible.

Good patterns:

- One launcher or Makefile owns the supported operator commands.
- One Compose file or generated manifest owns each service boundary.
- One generator owns generated run manifests, Dockerfiles, or install snippets.
- One no-write check proves generated output is current.
- One update command refreshes generated output deliberately.
- Tests inspect the rendered or generated artifact, not a hand-copied policy.

Bad patterns:

- A README command, Make target, CI job, and generated manifest each contain a
  slightly different hardening posture.
- Docker and Podman commands diverge accidentally instead of through documented
  engine-specific flags.
- A check validates a simplified fixture while users run a different command.
- Updating dependencies, generated manifests, or launch commands happens as a
  side effect of a normal check/test command.

## CI and release

Local lanes and CI lanes should converge. CI should run the same container-backed
targets operators run locally, not a separate host-toolchain recreation unless
there is a specific reason.

Default CI should include:

- Offline source checks.
- Build and test lanes.
- Package or release-artifact validation when the project publishes artifacts.
- Generated-output drift checks.

Default CI should not include:

- Live external-network proofs unless the runner and failure mode are designed
  for them.
- Long performance benchmarks.
- Public preview services.
- Broad cleanup commands.
- Dependency metadata updates.

Release lanes need their own boundary:

- Build artifacts in a controlled container lane.
- Validate archives before publishing: paths, symlinks, special files, expected
  package trees, generated metadata, and checksums.
- Treat publishing credentials as release-only secrets.
- Keep local package validation separate from registry push.
- Prefer immutable image refs and verify pushed digest matches the local
  artifact digest.
- Do not let release automation publish arbitrary files from a directory; use
  an allowlist.

## Maintenance

Container posture decays unless it is maintained deliberately.

Schedule or document these reviews:

- Host/runtime refresh: keep the host kernel, Docker/Podman engine, low-level
  runtime, rootless networking stack, and Compose/launcher tooling current.
- Image refresh: rebuild pinned images, review base-image digests, and check
  whether the base family is still maintained.
- Toolchain refresh: review direct tool versions, scanners, package managers,
  compiler images, and generated launch manifests.
- Dependency refresh: run explicit update mode, review lock/checksum/source
  diffs, then run installed dependency verification before build/test lanes.
- Exception review: remove stale network, device, mount, secret, port, and
  socket exceptions.
- Secret review: rotate release credentials and remove secrets from volumes or
  profiles that no longer need them.
- State review: list persistent volumes, local services, published ports,
  profiles, images, and caches; remove what is no longer needed.
- Proof review: make sure checks still inspect the artifact users actually run.

Keep maintenance commands separate from routine checks. A check should report
drift; an update or cleanup command should change state deliberately.

## Incident response

If a lane may have run hostile or unexpected code, assume anything granted to
that lane may be compromised.

First actions:

- Stop the lane's services and interactive sessions.
- Revoke or rotate secrets that were mounted, passed through env, present in
  volumes, or reachable through protocol tools.
- Remove the lane's named volumes and caches unless they are needed for
  investigation.
- Rebuild images from known pins and clean build context.
- Re-run dependency verification, generated-output drift checks, and source
  policy checks.
- Inspect writable outputs owned by the lane before trusting build/test or
  release results.
- If the lane had network, review what it could read and where it was allowed
  to connect.

Do not treat container deletion as cleanup of all risk. Writable bind mounts,
named volumes, pushed artifacts, published packages, logs, local services, and
external credentials can outlive the container.

## Reject immediately

These patterns should fail review unless documented as exceptions:

- A networked dependency tool has repo-root read/write access.
- A routine check/test lane mounts a container-engine socket.
- A service uses `privileged: true`, host network, host PID, or host IPC.
- A remote container-engine API is reachable over unauthenticated TCP or a
  broad local network.
- A service disables default seccomp, AppArmor, or SELinux confinement without
  a written exception.
- A host-published port binds to `0.0.0.0` by accident.
- A generated command uses publish-all port behavior such as `-P`.
- A generated launch command lacks the hardening posture expected for the
  equivalent manual run.
- A launcher silently falls back to a weaker engine, user namespace, network,
  mount, image, or secret posture.
- A dependency install command can update locks or metadata by default.
- A package-manager install stage relies on lifecycle scripts without a written
  reason.
- A Dockerfile uses remote URL `ADD` as an undeclared dependency path.
- An image build performs dependency updates or network fetches outside an
  explicit networked build/dependency lane.
- A lane writes into a symlinked output directory.
- A build context includes `.env`, SSH material, cloud config, Docker config,
  package-manager tokens, virtualenvs, caches, or generated release artifacts.
- A vulnerability review says "no advisories found" without stating whether it
  checked declared pins, lock state, built images, or all three.
- A long-running service has unbounded logs or logs credential-bearing payloads.
- A cleanup command removes containers, volumes, networks, compose projects, or
  tagged images without saying so in its name and status output.

## Checks to add

Use repository checks to freeze the container contract. Good checks include:

- No checked-in Compose file sets a top-level project `name:`.
- No service uses `privileged: true`, host network, host PID/IPC,
  container-engine sockets, broad devices, added capabilities, or broad group
  additions without a named exception.
- Remote engine access, if present, uses SSH or mutually authenticated TLS and
  treats client credentials as high-privilege secrets.
- No service disables seccomp, AppArmor, or SELinux confinement without a named
  exception.
- Default check/test services are read-only, non-root, capability-free,
  resource-bounded, and networkless.
- Writable lanes mount only their owned artifact paths.
- Bind mounts set `create_host_path: false` where implicit creation is risky.
- Published ports are bound to `127.0.0.1` unless explicitly public.
- External images and base images are fully qualified and digest-pinned.
- Checked-in workflows do not use unqualified image short names.
- Pull behavior is explicit for generated commands and CI lanes.
- Image signature, attestation, provenance, or SBOM verification is explicit
  when the project claims to rely on it.
- Build contexts exclude local secrets and generated artifacts.
- Dockerfile `ENV`, labels, and image metadata do not contain secrets.
- Build-time network mode is explicit where image builds are part of the
  workflow.
- Remote URL `ADD` is rejected unless it is a documented exception.
- Build cache mounts are scoped and do not store secrets.
- Lockfiles are present and not excluded from image build contexts.
- Dependency source policy rejects unexpected registries, URLs, archive shapes,
  and import paths.
- Package metadata policy rejects unsupported package-manager files, nested
  locks, symlinked manifests, unreviewed package-manager config files, and
  non-exact dependency versions.
- Package lock policy checks registry host, HTTPS tarball shape, integrity
  metadata, and workspace-link shape.
- Generated manifests, Dockerfiles, launch commands, and release artifacts have
  no-write drift checks.
- Container-backed checks themselves do not depend on host package managers.
- Root guards, port validators, env parsers, and mount validators have tests.
- Engine checks verify the promised engine posture, such as rootless Podman
  when a lane documents rootless Podman as its safer path.
- Podman user namespace mode is explicit for generated commands, especially
  `auto` versus `keep-id`.
- Engine-specific generated commands are checked for every supported engine.
- Fallback behavior is checked: missing rootless Podman or missing user
  namespace support must fail closed or require an explicit weaker profile.
- Broad generated-directory stagers validate their exact supported source and
  destination paths.
- Toolchain image pin checks cover every image family used by the lanes, not
  only the primary runtime image.
- Policy tests include self-check fixtures that prove the classifier accepts a
  known-good example and rejects known-bad examples.
- Long-running services have bounded logs and no credential-bearing log output
  by design.

Use rendered-configuration checks when string checks are too weak. For Compose,
prefer checking `docker compose config --format json` for service sets, merged
profiles, rendered ports, mounts, networks, and posture.

String checks are acceptable for simple repo-text policy, but they should not
be the only proof for lifecycle behavior. If the bug would appear only after
profile merging, variable interpolation, generated manifests, or wrapper
scripts, test the rendered or generated result.

## Housekeeping

Keep cleanup conservative:

- Prune dangling images.
- Prune old builder cache.
- Do not remove containers, volumes, networks, compose projects, tagged images,
  or release artifacts in a routine cleanup target.
- Put periodic cleanup behind a systemd timer plus one-shot service when it
  needs to run unattended.
- Make the cleanup command direct and narrow; avoid timers that call broad
  project targets.
- Add journal size limits on small servers.

Prefer cleanup commands that print their exclusions. A good cleanup message says
what will be removed and, just as importantly, that containers, volumes,
networks, tagged images, and release artifacts are not in scope.

## Exceptions

Sometimes a lane really does need a broader capability. Make that exception
hard to add casually.

Document each exception with:

- The capability being added: network, device, writable mount, secret, port,
  container-engine socket, host namespace, or extra Linux capability.
- The exact command or service that receives it.
- Why the narrower posture fails.
- The host paths, devices, ports, or domains in scope.
- The check that prevents accidental expansion.
- The cleanup or revocation path.
- The review date or condition for removing the exception.

Prefer one narrow exception lane over weakening a shared base service. For
example, do not add network to a shared test base if only one integration test
needs a local service.

## Lane record template

For any non-trivial lane, document this in the Makefile help, repo docs, or a
nearby note:

```text
Lane:
Purpose:
Entrypoint:
Image(s):
Source boundary:
Writable outputs:
Network:
Secrets:
Devices:
Ports:
Persistent state:
Runtime posture:
Update mode:
Checks/proofs:
Residual risks:
Maintenance:
Cleanup:
Incident response:
Known exceptions:
```

The record should be short enough to keep current. Its job is to make the trust
boundary reviewable before someone reads the full Compose file.

## Review checklist

Use this checklist when adding or reviewing a container lane.

### Purpose

- [ ] The lane has a clear purpose and belongs in the supported entrypoint.
- [ ] Its name reflects cost and risk: offline, runtime, live, dependency,
      package, service, or interactive.
- [ ] It is separate from other lanes when its trust boundary differs.
- [ ] The docs say what it reads, writes, reaches, and starts.
- [ ] The docs state the lane's residual risk: what malicious code could still
      do with the authority intentionally granted.

### Runtime posture

- [ ] Runs as non-root.
- [ ] Refuses root host execution where host writes are possible.
- [ ] Uses rootless Podman for lower-trust interactive lanes where available,
      or documents why a different engine is used.
- [ ] Podman lanes choose `--userns=auto` or `--userns=keep-id` deliberately.
- [ ] Podman lanes fail closed when required rootless or user namespace support
      is unavailable.
- [ ] Docker and Podman generated commands are both checked when both engines
      are supported.
- [ ] Stronger isolation runtimes, if promised, are verified and do not silently
      fall back to ordinary native containers.
- [ ] Uses `read_only: true` or `--read-only`.
- [ ] Drops all capabilities.
- [ ] Sets `no-new-privileges:true`.
- [ ] Sets memory, CPU, and PID bounds.
- [ ] Uses tmpfs for `/tmp` and caches.
- [ ] Does not use privileged mode, host network, or host PID/IPC.
- [ ] Does not disable default seccomp, AppArmor, or SELinux confinement without
      a documented exception.
- [ ] Does not mount container-engine sockets, including Docker and Podman
      sockets, unless the lane is explicitly a container-management lane.
- [ ] Remote engine credentials are treated as high-privilege secrets.
- [ ] Adds devices only behind an explicit mode and documentation.
- [ ] Does not mount `/dev` wholesale.
- [ ] Resource bounds are configurable without removing defaults.

### Filesystem

- [ ] Read-only source inspection uses a read-only bind mount.
- [ ] Build/package validation uses copied build context where practical.
- [ ] Writable bind mounts are limited to lane-owned outputs.
- [ ] Writable host paths are checked for symlinks and expected type.
- [ ] Mount destinations are fixed and narrow.
- [ ] Host home, SSH, cloud config, Docker config, package-manager config, and
      agent config are not mounted by default.
- [ ] Persistent state uses a named volume when it should survive sessions.
- [ ] Persistent volumes are managed through the engine, not by assuming a
      stable host storage path.
- [ ] SELinux bind-mount labels are explicit on SELinux hosts.
- [ ] Interactive sessions have profile, status, attach, stop, and reset/remove
      operations.

### Network

- [ ] Default network is `none` for lanes that do not need it.
- [ ] Networked workers do not have repo-root write access.
- [ ] Egress is proxied or otherwise allowlisted when practical.
- [ ] Local/private/link-local/metadata destinations are blocked for internet
      egress lanes.
- [ ] Inbound ports are absent unless the lane is explicitly a service.
- [ ] Published local ports bind to `127.0.0.1`.
- [ ] Publish-all behavior such as `-P` is not used.
- [ ] Protocol proxies enforce method/tool allowlists when read-only behavior
      matters.
- [ ] A live allow/deny check exists for important egress policy.
- [ ] Rootless Podman networking, if supported, is tested with the actual
      generated command rather than assumed from Docker behavior.

### Dependencies

- [ ] Default install is locked and must not change dependency metadata.
- [ ] Metadata updates require an explicit flag such as `ALLOW_UPDATE=1`.
- [ ] Build-time dependency installation has the same source and network review
      as runtime dependency installation.
- [ ] Installer, verifier/patcher, and offline apply responsibilities are split
      when they need different toolchains.
- [ ] Networked stage receives only minimal input files.
- [ ] Workspace package-manager stages receive a copied temporary manifest tree,
      not the real repository root.
- [ ] Offline apply writes only expected dependency outputs.
- [ ] Offline apply pre-validates writable targets and rejects symlinks or
      wrong file types.
- [ ] Upstream archives/packages are verified against lockfile checksums or
      equivalent integrity metadata.
- [ ] Source policy rejects unexpected registries, URLs, archive shapes, and
      package manager drift.
- [ ] Lifecycle scripts are disabled unless deliberately required.
- [ ] Installed dependency contents are verified before build/test.
- [ ] Package lock checks verify registry source, HTTPS tarball shape, and
      integrity metadata.

### Images and supply chain

- [ ] Base images are fully qualified and pinned by digest.
- [ ] External images do not rely on short-name resolution.
- [ ] Pull behavior is explicit for routine checks, update lanes, and release
      lanes.
- [ ] Image signature, attestation, provenance, or SBOM verification is checked
      when claimed by the lane.
- [ ] Provenance policy checks expected builder, source revision, materials,
      build parameters, platform, and produced digest when provenance is used.
- [ ] Tool versions are explicit.
- [ ] Package requirements are locked or hash-checked where the ecosystem
      supports it.
- [ ] `.dockerignore` excludes secrets, local state, caches, and generated
      artifacts.
- [ ] Required lockfiles and source manifests are included in the build context.
- [ ] Build images remove package managers from runtime images when they are not
      needed at runtime.
- [ ] Generated Dockerfiles or launch manifests have drift checks.
- [ ] Build-time network mode is explicit, and networked build stages are
      treated as dependency or secret lanes.
- [ ] Remote URL `ADD` is not used as an undeclared dependency mechanism.
- [ ] Build cache mounts are scoped, non-secret, and removable.
- [ ] Final image configuration is inspected for user, env, labels, exposed
      ports, entrypoint, and copied runtime files.
- [ ] Vulnerability review distinguishes declared pins, lock state, and built
      image contents.

### Secrets

- [ ] Secrets are runtime inputs, not image contents.
- [ ] Secret files are mounted read-only and narrowly.
- [ ] Temporary secret files are mode-restricted and removed by traps.
- [ ] Logs and generated manifests do not include secret values.
- [ ] Agent or protocol tool arguments are treated as visible to the local host.

### Logs

- [ ] Long-running services have bounded log growth.
- [ ] Logs do not include secrets, credential-bearing command lines, or
      sensitive protocol payloads.
- [ ] Cleanup and incident-response notes state whether logs are in scope.

### Tests and proofs

- [ ] Offline repository checks cover the posture contract.
- [ ] Runtime checks render and inspect merged configuration where needed.
- [ ] Live checks prove at least one expected success and one expected failure
      for critical network policy.
- [ ] Generated outputs have no-write drift checks and explicit regenerate
      commands.
- [ ] The narrowest relevant container-backed check is documented for reviewers.

### Operations

- [ ] `doctor` or equivalent status output shows selected engine, rootless
      status, network mode, mount mode, profiles, and persistent volumes where
      relevant.
- [ ] Cleanup commands state what they remove and what they deliberately leave
      alone.
- [ ] Maintenance/update commands are separate from routine check/test lanes.
- [ ] The lane's persistent state and secrets have a removal or rotation path.
- [ ] Incident response notes identify which outputs, volumes, secrets,
      services, and network destinations were in scope.

### CI and release

- [ ] CI uses the same documented container-backed lanes as local development.
- [ ] Live checks, performance lanes, and public previews are opt-in, not hidden
      inside default CI.
- [ ] Release artifacts are validated before publishing.
- [ ] Publish commands use explicit allowlists and immutable artifact or image
      references.
- [ ] Publishing credentials are not available to ordinary check/test lanes.

## Rollout plan

For a new project, add lanes in this order:

1. Add the minimum architecture and make `checks` pass.
2. Add posture tests for Compose, Dockerfiles, `.dockerignore`, root guards, and
   forbidden host escape hatches.
3. Add copied-context or read-only test lanes.
4. Add package or artifact validation lanes.
5. Add dependency stage/apply lanes only when dependency installation is needed.
6. Add runtime checks for rendered Compose, profiles, ports, and generated
   launch commands.
7. Add live external-network allow/deny checks last.
8. Add release/publish lanes only after local artifact validation is routine.

Each step should leave a passing check behind. Do not add a broader capability
without adding the check that would catch it expanding later.

## Definition of done

A containerized lane is not done when the command works once. It is done when:

- Its purpose, inputs, outputs, network, secrets, devices, ports, and state are
  documented.
- Its runtime posture is encoded in the launcher or Compose file.
- Its writable host paths are narrow and prevalidated.
- Its network and secret exposure are no broader than the purpose requires.
- Its generated outputs, if any, have a no-write drift check or an explicit
  update mode.
- Its posture is covered by offline repository checks, rendered runtime checks,
  or live allow/deny checks as appropriate.
- Its persistent state, exceptions, secrets, and pinned images have a documented
  maintenance path.
- Its incident response notes identify what must be revoked, removed, rebuilt,
  or reverified if the lane runs hostile code.
- The narrowest relevant container-backed check passes from a clean tree.
