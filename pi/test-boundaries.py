"""Executable regression checks; Docker mode never executes candidate code on host."""
import argparse
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("controller", ROOT / "controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def archive(path, code):
    with tarfile.open(path, "w") as output:
        for name, text in {"duration.py": code, ".agent/STATE.md": "# Objective\n# Tests\n"}.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            output.addfile(member, io.BytesIO(data))


parser = argparse.ArgumentParser()
parser.add_argument("--candidate", type=Path, help="Also test verifier in Docker against this saved candidate")
args = parser.parse_args()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    fifo = root / "fifo"
    os.mkfifo(fifo)
    try:
        c.Trial.read_input(fifo, 10, "test")
        raise AssertionError("FIFO accepted")
    except ValueError:
        pass
    regular = root / "large"
    regular.write_bytes(b"x" * 11)
    try:
        c.Trial.read_input(regular, 10, "test")
        raise AssertionError("Oversized input accepted")
    except ValueError:
        pass
    print("PASS FIFO and oversized input rejected")
    if args.candidate:
        trial = c.Trial(SimpleNamespace(timeout=300, task=ROOT / "fixtures/task.txt",
                        verifier=ROOT / "fixtures/checks/verify.py"))
        print("Artifacts:", trial.directory)
        try:
            for name, code in {
                "early-exit": "import os; os._exit(0)",
                "monkeypatch": "import unittest\nunittest.TestCase.assertEqual = lambda *a: None\ndef parse_duration(x): return 0",
                "unfinished": "def parse_duration(x): raise NotImplementedError()",
            }.items():
                candidate = root / (name + ".tar")
                archive(candidate, code)
                status, _ = trial.verify(candidate, name)
                assert status != 0, f"Verifier accepted {name}"
                print("PASS rejected", name)
            status, _ = trial.verify(args.candidate.resolve(), "actual-candidate")
            assert status == 0, "Real candidate failed qualification"
            print("PASS real candidate independently qualified")
        finally:
            # No agent or relay is created by this test.
            for name in trial.containers:
                c.docker("rm", "-f", name)
