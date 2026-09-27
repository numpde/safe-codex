#!/usr/bin/env python3
"""Host-side controller. Untrusted project/model code runs only inside Docker."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import tarfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
PYTHON_IMAGE = "python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"
MIB = 1024 * 1024
MAX_ARCHIVE = 600 * MIB
MAX_ARCHIVE_MEMBERS = 10_000
MAX_PREVIEW_TEXT = 16 * MIB


def command(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=kwargs.pop("timeout", 60), **kwargs)


def docker(*args, **kwargs):
    return command(["docker", *map(str, args)], **kwargs)


def capture(args, destination, limit=MAX_ARCHIVE, timeout=90, deadline=None):
    """Bound both archive output and runtime; never unpack archives on the host."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if deadline is not None:
        timeout = min(timeout, max(0.1, deadline - time.monotonic()))
    timer = threading.Timer(timeout, process.kill)
    timer.start()
    total = 0
    try:
        with destination.open("wb") as stream:
            while data := process.stdout.read(1024 * 1024):
                total += len(data)
                if total > limit:
                    raise RuntimeError("Artifact exceeded its size limit")
                stream.write(data)
        if process.wait() != 0:
            raise RuntimeError("Artifact capture failed or timed out")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()


def archive_files(path, deadline=None):
    """Small text files only, for review/state; tar members are never extracted."""
    result = {}
    total = 0
    members = 0
    with tarfile.open(path) as archive:
        for member in archive:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Task wall-clock limit reached")
            members += 1
            if members > MAX_ARCHIVE_MEMBERS:
                raise RuntimeError("Archive has too many members")
            name = member.name.removeprefix("./")
            if (not member.isfile() or member.size > MIB or name.startswith("/")
                    or ".." in Path(name).parts or ".git" in Path(name).parts):
                continue
            content = archive.extractfile(member).read(MIB + 1)
            if b"\0" not in content:
                total += len(content)
                if total > MAX_PREVIEW_TEXT:
                    raise RuntimeError("Archive text preview exceeds its size limit")
                result[name] = content.decode("utf-8", errors="replace")
    return result


def make_diff(baseline, candidate, deadline=None):
    before, after = archive_files(baseline, deadline), archive_files(candidate, deadline)
    pieces = []
    length = 0
    for name in sorted(before.keys() | after.keys()):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Task wall-clock limit reached")
        if before.get(name) == after.get(name):
            continue
        part = "".join(difflib.unified_diff(before.get(name, "").splitlines(True),
                                           after.get(name, "").splitlines(True),
                                           fromfile="before/" + name, tofile="after/" + name))
        length += len(part)
        if length > 2 * MIB:
            pieces.append("\n[Diff preview truncated; inspect candidate.tar for the full snapshot.]\n")
            break
        pieces.append(part)
    return "".join(pieces), after.get(".agent/STATE.md", "")


def hardened(name, image, network="none", workspace_tmpfs=True):
    args = ["run", "-d", "--pull", "never", "--name", name, "--init",
            "--label", "safe-pi.managed=true", "--network", network,
            "--read-only", "--user", "1000:1000", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "2g", "--memory-swap", "2g",
            "--cpus", "2", "--pids-limit", "128", "--ulimit", "nofile=1024:1024",
            "--log-opt", "max-size=10m", "--log-opt", "max-file=1",
            "--tmpfs", "/home/pi:rw,nosuid,nodev,noexec,size=32m,nr_inodes=4096,uid=1000,gid=1000",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m,nr_inodes=8192",
            "--tmpfs", "/sessions:rw,nosuid,nodev,noexec,size=64m,nr_inodes=4096,uid=1000,gid=1000"]
    if workspace_tmpfs:
        args.extend(["--tmpfs", "/workspace:rw,nosuid,nodev,size=512m,nr_inodes=65536,uid=1000,gid=1000"])
    return args


class RPC:
    def __init__(self, container, directory, deadline):
        self.deadline = deadline
        self.events = queue.Queue(maxsize=512)
        self.stopped = threading.Event()
        self.counter = 0
        self.process = subprocess.Popen(
            ["docker", "exec", "-i", "--env", "SAFE_PI_QUALIFICATION=1",
             container, "/opt/safe-pi/entrypoint.sh", "--mode", "rpc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.log = (directory / "events.jsonl").open("wb")
        self.error_log = (directory / "pi-stderr.log").open("wb")
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.read_errors, daemon=True).start()

    def enqueue(self, value):
        while not self.stopped.is_set():
            try:
                self.events.put(value, timeout=0.2)
                return
            except queue.Full:
                continue

    def read_errors(self):
        total = 0
        while data := self.process.stderr.read(4096):
            total += len(data)
            if total <= 2 * MIB:
                self.error_log.write(data)
                self.error_log.flush()

    def read(self):
        logged = 0
        try:
            while line := self.process.stdout.readline(2 * MIB + 1):
                if len(line) > 2 * MIB:
                    raise RuntimeError("RPC line exceeded limit")
                value = json.loads(line)
                if value.get("type") == "message_update":
                    continue
                logged += len(line)
                if logged > 64 * MIB:
                    raise RuntimeError("RPC event log exceeded limit")
                self.log.write(line)
                self.log.flush()
                self.enqueue(value)
        except Exception as error:
            self.enqueue({"type": "controller_error", "error": str(error)})
        finally:
            self.enqueue({"type": "controller_eof"})

    def send(self, kind, **values):
        self.counter += 1
        identifier = f"controller-{self.counter}"
        self.process.stdin.write((json.dumps({"id": identifier, "type": kind, **values}) + "\n").encode())
        self.process.stdin.flush()
        return identifier

    def next(self):
        while time.monotonic() < self.deadline:
            try:
                event = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if event.get("type") in ("controller_error", "controller_eof"):
                raise RuntimeError(event.get("error", "Pi exited; inspect pi-stderr.log"))
            if event.get("type") == "response" and not event.get("success", True):
                raise RuntimeError("Pi RPC rejected a command: " + str(event.get("error")))
            return event
        raise TimeoutError("Task wall-clock limit reached")

    def call(self, kind, **values):
        identifier = self.send(kind, **values)
        while True:
            event = self.next()
            if event.get("type") == "response" and event.get("id") == identifier:
                return event.get("data", {})

    def prompt(self, message, checkpoint=False):
        self.send("prompt", message=message)
        turns, tokens = 0, 0
        calls, failures = {}, {}
        restart = None
        error = None
        abort_sent = False
        while True:
            event = self.next()
            kind = event.get("type")
            if kind == "tool_execution_start":
                calls[event.get("toolCallId")] = json.dumps(
                    [event.get("toolName"), event.get("args")], sort_keys=True)
                print("Tool:", event.get("toolName"), flush=True)
            elif kind == "tool_execution_end" and event.get("isError"):
                key = calls.get(event.get("toolCallId"))
                failures[key] = failures.get(key, 0) + 1
                if failures[key] >= 2:
                    restart = "Repeated failing tool call"
            elif kind == "turn_end":
                turns += 1
                msg = event.get("message", {})
                usage = msg.get("usage", {})
                tokens = usage.get("totalTokens") or sum(usage.get(k, 0) for k in
                                                         ("input", "output", "cacheRead", "cacheWrite"))
                if msg.get("stopReason") == "error":
                    error = msg.get("errorMessage", "Inference error")
                if not checkpoint and tokens >= 44000:
                    restart = "Context checkpoint threshold"
                if not checkpoint and msg.get("stopReason") == "length":
                    restart = "Output limit reached"
                if turns >= (4 if checkpoint else 80):
                    restart = "Turn limit reached"
            if restart and not abort_sent and kind != "agent_settled":
                self.send("abort")
                abort_sent = True
            if kind == "agent_settled":
                return {"restart": restart, "error": error, "tokens": tokens, "turns": turns}


class Trial:
    def __init__(self, args):
        self.args = args
        self.backend = getattr(args, "backend", "vllm")
        self.workspace_mode = getattr(args, "workspace_mode", "copy")
        self.model = "qwen3.8-flash-next" if self.backend == "exl3" else "qwen3.8-27b"
        self.identifier = "safe-pi-" + uuid.uuid4().hex[:12]
        self.directory = ROOT / "results" / self.identifier
        self.directory.mkdir(parents=True, mode=0o700)
        self.image = (ROOT / ".build/runtime-image-id").read_text().strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image):
            raise ValueError("Invalid built image ID; run pi/build.sh")
        docker("image", "inspect", self.image)
        self.agent = self.identifier + "-agent"
        self.relay = self.identifier + "-relay"
        self.volume = self.identifier + "-socket"
        self.volume_created = False
        self.containers = []
        self.rpc = None
        self.paused = False
        self.deadline = time.monotonic() + args.timeout
        self.baseline = self.directory / "baseline.tar"
        self.verifier = self.directory / "verify.py"
        if getattr(args, "agent_only", False):
            return
        code = self.read_input(args.verifier, MIB, "Verifier")
        if len(code) > MIB:
            raise ValueError("Verifier is too large")
        self.verifier.write_bytes(code)
        self.task = self.read_input(args.task, 32768 * 4, "Task").decode("utf-8")
        if len(self.task) > 32768:
            raise ValueError("Task exceeds 32768 characters")
        (self.directory / "task.txt").write_text(self.task)

    @staticmethod
    def read_input(path, limit, label):
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            if not os.stat(fd).st_mode & 0o170000 == 0o100000:
                raise ValueError(f"{label} is not a regular file: {path}")
            data = os.read(fd, limit + 1)
        finally:
            os.close(fd)
        if len(data) > limit:
            raise ValueError(f"{label} exceeds its size limit")
        return data

    def start_container(self, name, extra, network="none", image=None,
                        workspace_tmpfs=True):
        self.containers.append(name)
        docker(*hardened(name, image or self.image, network, workspace_tmpfs), *extra,
               "--entrypoint", "/bin/sleep", image or self.image, "infinity")

    def prepare(self):
        if self.workspace_mode == "copy":
            try:
                command(["git", "-C", str(self.args.repo), "rev-parse", "--verify", "HEAD^{commit}"])
            except subprocess.CalledProcessError as error:
                raise ValueError(f"Workspace must be a Git repository with a committed HEAD: {self.args.repo}") from error
        elif self.workspace_mode != "ro":
            raise ValueError(f"Unsupported workspace mode: {self.workspace_mode}")
        for path in (ROOT, self.directory):
            if any(character in str(path) for character in (",", "\n")):
                raise ValueError("Unsupported comma/newline in mount path")
        if self.backend == "vllm":
            network = json.loads(docker("network", "inspect", "proart-vllm_inference").stdout)[0]
            if not network.get("Internal"):
                raise RuntimeError("Inference network must be internal")
        else:
            try:
                docker("volume", "inspect", "proart-exl3_inference")
                # Existence of the external volume does not mean the model
                # process is listening. Probe the socket before starting a
                # relay whose requests would otherwise hang until timeout.
                docker("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                       "--user", "1000:1000", "--cap-drop", "ALL",
                       "--security-opt", "no-new-privileges", "--memory", "64m",
                       "--memory-swap", "64m", "--cpus", "0.25", "--pids-limit", "16",
                       "--mount", "type=volume,src=proart-exl3_inference,dst=/inference,readonly",
                       "--entrypoint", "python", PYTHON_IMAGE, "-c",
                       "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect('/inference/api.sock')")
            except subprocess.CalledProcessError as error:
                raise RuntimeError("EXL3 server is not ready; start ../proart-llm/bin/exl3-server start") from error
        if self.workspace_mode == "copy":
            capture(["git", "-C", str(self.args.repo), "archive", "--format=tar", "HEAD"],
                    self.baseline, deadline=self.deadline)
        docker("volume", "create", "--label", "safe-pi.managed=true", self.volume)
        self.volume_created = True
        docker("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--cap-add", "CHOWN", "--security-opt", "no-new-privileges",
               "--mount", f"type=volume,src={self.volume},dst=/relay", "--entrypoint", "/bin/sh",
               PYTHON_IMAGE, "-c", "chmod 700 /relay && chown 1000:1000 /relay")
        self.containers.append(self.relay)
        relay_network = "proart-vllm_inference" if self.backend == "vllm" else "none"
        relay_extra = (["--mount", "type=volume,src=proart-exl3_inference,dst=/upstream,readonly"]
                       if self.backend == "exl3" else [])
        docker("run", "-d", "--pull", "never", "--name", self.relay,
               "--label", "safe-pi.managed=true", "--network", relay_network,
               "--env", f"SAFE_PI_BACKEND={self.backend}", *relay_extra,
               "--read-only", "--user", "1000:1000", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--memory", "128m", "--memory-swap", "128m",
               "--cpus", "0.5", "--pids-limit", "32", "--log-opt", "max-size=10m", "--log-opt", "max-file=1",
               "--mount", f"type=volume,src={self.volume},dst=/relay",
               "--mount", f"type=bind,src={ROOT / 'relay.py'},dst=/relay.py,readonly",
               PYTHON_IMAGE, "python", "-B", "/relay.py")
        agent_extra = ["--env", f"SAFE_PI_MODEL={self.model}",
                       "--env", f"SAFE_PI_WORKSPACE_MODE={self.workspace_mode}",
                       "--mount", f"type=volume,src={self.volume},dst=/relay,readonly"]
        if self.workspace_mode == "ro":
            agent_extra.extend(["--env", "GIT_OPTIONAL_LOCKS=0", "--mount",
                                f"type=bind,src={self.args.repo},dst=/workspace,readonly"])
        self.start_container(self.agent, agent_extra,
                             workspace_tmpfs=self.workspace_mode == "copy")
        for _ in range(50):
            try:
                docker("exec", self.agent, "test", "-S", "/relay/api.sock", timeout=2)
                break
            except subprocess.CalledProcessError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Inference relay did not become ready")
        if self.workspace_mode == "copy":
            with self.baseline.open("rb") as source:
                docker("exec", "-i", self.agent, "tar", "-xf", "-", "-C", "/workspace", stdin=source)
            docker("exec", "-w", "/workspace", self.agent, "/bin/sh", "-c",
                   "git init -q && git -c core.hooksPath=/dev/null add -A && "
                   "git -c user.name=Snapshot -c user.email=snapshot@local -c core.hooksPath=/dev/null commit -qm baseline")
        probe = docker("exec", "-i", self.agent, "python3", "-", input=(ROOT / "isolation-test.py").read_bytes())
        (self.directory / "isolation.log").write_bytes(probe.stdout)
        print(probe.stdout.decode(), end="", flush=True)

    def snapshot(self, number, preview=True, include_workspace=True):
        docker("pause", self.agent)
        self.paused = True
        candidate = self.directory / f"candidate-{number}.tar"
        # Docker cp omits tmpfs mounts. A trusted helper joins only the PID
        # namespace and reads the paused init's mount tree, without capabilities.
        artifacts = [("sessions", self.directory / f"sessions-{number}.tar", 80 * MIB)]
        if include_workspace:
            artifacts.insert(0, ("workspace", candidate, MAX_ARCHIVE))
        for folder, destination, limit in artifacts:
            name = self.identifier + "-snapshot-" + folder
            self.containers.append(name)
            args = ["docker", "run", "--rm", "--pull", "never", "--name", name,
                    "--network", "none", "--read-only", "--user", "1000:1000",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--memory", "128m", "--memory-swap", "128m", "--pids-limit", "16",
                    "--pid", f"container:{self.agent}", "--entrypoint", "/bin/tar",
                    self.image, "-cf", "-", "-C", f"/proc/1/root/{folder}", "."]
            capture(args, destination, limit=limit, deadline=self.deadline)
            self.containers.remove(name)
        if not preview or not include_workspace:
            return candidate, "", ""
        preview, state = make_diff(self.baseline, candidate, self.deadline)
        (self.directory / "changes.diff").write_text(preview)
        (self.directory / "STATE.md").write_text(state)
        return candidate, preview, state

    def verify(self, candidate, number):
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Task wall-clock limit reached")
        name = self.identifier + f"-verify-{number}"
        self.start_container(name, ["--mount", f"type=bind,src={self.verifier},dst=/checks/verify.py,readonly"])
        timer = threading.Timer(max(0.1, min(120, self.deadline - time.monotonic())),
                                lambda: subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL,
                                                       stderr=subprocess.DEVNULL, timeout=10))
        timer.daemon = True
        timer.start()
        try:
            with candidate.open("rb") as source:
                docker("exec", "-i", name, "tar", "-xf", "-", "-C", "/workspace",
                       stdin=source, timeout=max(1, min(60, self.deadline - time.monotonic())))
            process = subprocess.Popen(["docker", "exec", "-w", "/workspace", name,
                                        "python3", "-I", "/checks/verify.py"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = bytearray()
            try:
                while data := process.stdout.read(4096):
                    output.extend(data)
                    if len(output) > 2 * MIB:
                        docker("kill", name)
                        raise RuntimeError("Verifier output limit exceeded")
                status = process.wait()
            finally:
                timer.cancel()
            text = output.decode("utf-8", errors="replace")
            (self.directory / f"verifier-{number}.log").write_text(text)
            print(f"Independent verifier exit code: {status}", flush=True)
            return status, text
        finally:
            timer.cancel()
            docker("rm", "-f", name)
            self.containers.remove(name)

    def run(self):
        self.prepare()
        # Prove the qualification gate rejects the unfinished fixture when requested.
        if self.args.expect_initial_failure:
            status, _ = self.verify(self.baseline, "baseline")
            if status == 0:
                raise RuntimeError("Verifier accepted the deliberately unfinished baseline")
        self.rpc = RPC(self.agent, self.directory, self.deadline)
        state = self.rpc.call("get_state")
        (self.directory / "pi-state.json").write_text(json.dumps(state, indent=2))
        if state.get("thinkingLevel") != "xhigh":
            raise RuntimeError("Pi did not select xhigh")
        prompt = self.task
        for attempt in range(1, 5):
            outcome = self.rpc.prompt(prompt)
            if outcome["restart"]:
                print("Checkpoint:", outcome["restart"], flush=True)
                if outcome["tokens"] < 47000:
                    self.rpc.prompt("Checkpoint now: update .agent/STATE.md with the task, exact results, "
                                    "current uncertainty and remaining work, then stop. Do not implement further changes.",
                                    checkpoint=True)
            candidate, preview, ledger = self.snapshot(attempt)
            status, evidence = self.verify(candidate, attempt)
            if status == 0:
                return {"status": "passed", "attempt": attempt, "candidate": candidate.name,
                        "image": self.image, "verifier_sha256": hashlib.sha256(self.verifier.read_bytes()).hexdigest()}
            docker("unpause", self.agent)
            self.paused = False
            if outcome["restart"]:
                self.rpc.call("new_session")
                prompt = (self.task + "\nContinue in this fresh session. Read .agent/STATE.md.\n"
                          + "Controller's diff preview:\n" + preview[:32000]
                          + "\nLatest independent verification failure:\n" + evidence[-8000:])
            else:
                prompt = ("The independent verifier failed. Correct the task using this failure evidence, "
                          "update STATE.md, and rerun relevant checks.\n" + evidence[-8000:])
        return {"status": "failed", "reason": "Four bounded attempts exhausted"}

    def cleanup(self):
        errors = []
        if self.rpc:
            self.rpc.stopped.set()
        try:
            logs = docker("logs", self.relay, timeout=10).stdout
            (self.directory / "relay.jsonl").write_bytes(logs[:10 * MIB])
        except (subprocess.SubprocessError, OSError):
            pass
        for args in (["rm", "-f", name] for name in reversed(self.containers)):
            try:
                docker(*args, timeout=10)
            except (subprocess.SubprocessError, OSError) as error:
                errors.append(str(error))
        if self.volume_created:
            try:
                docker("volume", "rm", self.volume, timeout=10)
                self.volume_created = False
            except (subprocess.SubprocessError, OSError) as error:
                errors.append(str(error))
        if self.rpc and self.rpc.process.poll() is None:
            self.rpc.process.terminate()
            try:
                self.rpc.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.rpc.process.kill()
                self.rpc.process.wait(timeout=3)
        return errors


def main():
    parser = argparse.ArgumentParser(description="Independent, bounded task-verification harness.")
    parser.add_argument("--repo", type=Path, required=True, help="Copy committed HEAD only")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True, help="Trusted standalone Python verifier")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--expect-initial-failure", action="store_true")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 14400:
        parser.error("timeout must be 30..14400 seconds")
    trial = Trial(args)
    print("Artifacts:", trial.directory, flush=True)
    result = {"status": "failed"}

    def alarm(*_):
        raise TimeoutError("Task wall-clock limit reached")

    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        result = trial.run()
    except (Exception, KeyboardInterrupt) as error:
        result["reason"] = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            result["detail"] = error.stderr.decode(errors="replace")[-8000:]
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            errors = trial.cleanup()
            if errors:
                result["cleanup_errors"] = errors
                result["status"] = "failed"
        except (Exception, KeyboardInterrupt) as error:
            result.update(status="failed", cleanup_errors=[str(error)])
        finally:
            (trial.directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
