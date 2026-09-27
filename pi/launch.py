#!/usr/bin/env python3
"""Run Pi with native arguments inside the local inference sandbox."""
import argparse
from contextlib import redirect_stdout
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import termios
import time

from controller import ROOT, Trial, docker


def arguments(argv):
    argv = list(argv)
    if argv[:1] == ["run"]:
        argv.pop(0)
    tail = []
    if "--" in argv:
        split = argv.index("--")
        argv, tail = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(prog="safe-codex pi", description=__doc__, allow_abbrev=False,
        epilog="Pi arguments follow --: -p 'prompt' prints and exits; -c continues. "
               "With no Pi flags, a terminal opens interactive Pi.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(),
                        help="Repository to copy initially, or mount with --workspace-ro")
    parser.add_argument("--workspace-ro", action="store_const", const="ro",
                        dest="workspace_mode",
                        help="Mount the real repository read-only, including Git metadata")
    parser.add_argument("--workspace-rw", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--profile", default="default", help="Saved sandbox/session profile (default: default)")
    parser.add_argument("--backend", choices=("vllm", "exl3"), default="vllm")
    parser.add_argument("--timeout", type=int, default=14400, help="Run limit in seconds (30..14400)")
    args, native = parser.parse_known_args(argv)
    if args.workspace_rw:
        parser.error("Pi does not mount host workspaces read/write; omit the flag for an isolated writable copy")
    args.workspace_mode = args.workspace_mode or "copy"
    args.pi_args = native + tail
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.profile) or args.profile in (".", ".."):
        parser.error("profile must contain letters, numbers, dot, underscore or dash")
    if not 30 <= args.timeout <= 14400:
        parser.error("timeout must be 30..14400 seconds")
    args.repo = args.workspace.expanduser().resolve()
    args.agent_only = True
    return args


def profile_path(args):
    key = hashlib.sha256(os.fsencode(args.repo)).hexdigest()[:20]
    # Backend histories use different model/template semantics and must never
    # silently resume one another.
    return ROOT / "state" / f"{args.profile}-{args.backend}-{args.workspace_mode}-{key}"


def previous_run(profile, workspace_mode="copy"):
    pointer = profile / "latest"
    if not pointer.exists():
        return None
    name = Trial.read_input(pointer, 128, "Profile pointer").decode().strip()
    if not re.fullmatch(r"safe-pi-[a-f0-9]{12}", name):
        raise ValueError("Invalid profile pointer")
    previous = ROOT / "results" / name
    artifacts = ["sessions-session.tar"]
    if workspace_mode == "copy":
        artifacts.insert(0, "candidate-session.tar")
    for artifact in artifacts:
        if not (previous / artifact).is_file():
            raise ValueError("Saved profile is incomplete; use a new --profile")
    return previous


def restore(trial, previous, workspace_mode="copy"):
    if previous is None:
        return
    # Only the container extracts these archives. Its root and mounts stay fixed.
    artifacts = [("sessions", "sessions-session.tar")]
    if workspace_mode == "copy":
        artifacts.insert(0, ("workspace", "candidate-session.tar"))
    for folder, artifact in artifacts:
        docker("exec", trial.agent, "find", f"/{folder}", "-mindepth", "1", "-delete")
        with (previous / artifact).open("rb") as archive:
            docker("exec", "-i", trial.agent, "tar", "-xf", "-", "-C", f"/{folder}", stdin=archive)


def native_mode(pi_args):
    """Resolve explicit output mode using the pinned Pi parser's precedence."""
    mode = None
    printing = False
    arguments = iter(pi_args)
    for argument in arguments:
        if argument == "--":
            break
        if argument in ("-p", "--print"):
            printing = True
        if argument == "--mode":
            value = next(arguments, None)
            if value in ("text", "json", "rpc"):
                mode = value
    return mode if mode in ("json", "rpc") else "print" if printing else "interactive"


def native_stream_mode(pi_args):
    return native_mode(pi_args) != "interactive"


def terminal_command(trial, pi_args):
    # Preserve separate stdout/stderr for native print, JSON, and RPC modes.
    # A Docker TTY merges the streams. Other native flags (including -c and
    # an initial prompt) still need a terminal for Pi's interactive behavior.
    tty = (not native_stream_mode(pi_args) and
           sys.stdin.isatty() and sys.stdout.isatty())
    # Let Pi itself select interactive/print/JSON/RPC behavior from native flags.
    cmd = ["docker", "exec", "-it" if tty else "-i", "--env",
           "TERM=" + os.environ.get("TERM", "xterm-256color"),
           trial.agent, "/opt/safe-pi/entrypoint.sh", *pi_args]
    settings = termios.tcgetattr(sys.stdin.fileno()) if tty else None
    interrupted = False
    try:
        # Pi consumes piped input to EOF before non-RPC startup. An inherited
        # host terminal becomes an endless pipe through docker exec -i.
        # Preserve actual pipelines and RPC input, but close unused terminal
        # input for print mode (also when stdout is redirected).
        close_input = not tty and sys.stdin.isatty() and native_mode(pi_args) != "rpc"
        return subprocess.run(cmd, stdin=subprocess.DEVNULL if close_input else None).returncode
    except BaseException:
        interrupted = True
        raise
    finally:
        if settings is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, settings)
                if interrupted:
                    sys.stdout.write("\x1b[<u\x1b[?2026l\x1b[?2004l\x1b[?25h\x1b[0m\r\n")
                    sys.stdout.flush()
            except (OSError, termios.error):
                pass


def main(argv=None):
    os.umask(0o077)
    args = arguments(sys.argv[1:] if argv is None else argv)
    if args.workspace_mode == "ro":
        validator = ROOT.parent / "bin" / "safe-codex"
        checked = subprocess.run([validator, "--engine", "docker", "_validate-workspace",
                                  str(args.repo)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        if checked.returncode:
            print(checked.stderr.rstrip(), file=sys.stderr)
            return 2
        args.repo = Path(checked.stdout.strip())
    if args.backend != "vllm" and args.profile == "default":
        args.profile = "exl3"
    profile = profile_path(args)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.parent.chmod(0o700)
    profile.chmod(0o700)
    lock = (profile / "lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("safe-codex pi: this workspace/profile is already in use", file=sys.stderr)
        lock.close()
        return 1
    try:
        previous = previous_run(profile, args.workspace_mode)
        trial = Trial(args)
    except Exception as error:
        print(f"safe-codex pi: {error}", file=sys.stderr)
        lock.close()
        return 1
    print(f"safe-codex pi: {args.profile}; saved files: {trial.directory}", file=sys.stderr, flush=True)
    ready = False
    retain = False
    result = {"status": "failed"}

    def expired(*_):
        raise TimeoutError("Session time limit reached")

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"Signal {signum}")

    signal.signal(signal.SIGALRM, expired)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        # Launcher messages must not contaminate native -p/JSON/RPC stdout.
        with redirect_stdout(sys.stderr):
            trial.prepare()
            restore(trial, previous, args.workspace_mode)
        ready = True
        status = terminal_command(trial, args.pi_args)
        result.update(status="closed", exit_code=status)
    except (Exception, KeyboardInterrupt) as error:
        result["reason"] = str(error)
        print(f"safe-codex pi: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode(errors="replace")[-4000:], file=sys.stderr)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if ready:
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(signum, signal.SIG_IGN)
            trial.deadline = time.monotonic() + 180
            signal.setitimer(signal.ITIMER_REAL, 180)
            try:
                trial.snapshot("session", preview=False,
                               include_workspace=args.workspace_mode == "copy")
                temporary = profile / "latest.tmp"
                temporary.write_text(trial.identifier + "\n")
                temporary.replace(profile / "latest")
                result.update(sessions="sessions-session.tar")
                if args.workspace_mode == "copy":
                    result["candidate"] = "candidate-session.tar"
            except Exception as error:
                retain = True
                result.update(status="failed", export_error=str(error), retained_container=trial.agent)
                print(f"safe-codex pi: export failed; sandbox {trial.agent} retained for recovery: {error}", file=sys.stderr)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            errors = [] if retain else trial.cleanup()
            if errors:
                result.update(status="failed", cleanup_errors=errors)
                print(f"safe-codex pi: cleanup errors: {errors}", file=sys.stderr)
        except (Exception, KeyboardInterrupt) as error:
            result.update(status="failed", cleanup_errors=[str(error)])
            print(f"safe-codex pi: cleanup failed: {error}", file=sys.stderr)
        finally:
            (trial.directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            lock.close()
    return result.get("exit_code", 1) if result["status"] == "closed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
