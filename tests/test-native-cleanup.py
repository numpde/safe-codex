import fcntl
import os
import shutil
import signal
import subprocess
import sys
import time
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

helper = Path(__file__).resolve().parent.parent / 'bin' / 'cleanup-native-codex-cli'
loader = importlib.machinery.SourceFileLoader('cleanup', str(helper))
spec = importlib.util.spec_from_loader(loader.name, loader)
cleanup = importlib.util.module_from_spec(spec)
loader.exec_module(cleanup)


class NativeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.locks').mkdir()

    def payload(self, version, managed=True):
        path = self.root / version
        path.mkdir()
        if managed:
            (path / cleanup.MARKER).write_text('1\n')
        return path

    def test_deletes_only_older_managed_stable_payloads(self):
        old = self.payload('0.1.0')
        legacy = self.payload('0.2.0', managed=False)
        current = self.payload('0.3.0')
        newer = self.payload('0.4.0')
        prerelease = self.payload('0.1.0-beta')
        cleanup.cleanup(self.root, '0.3.0')
        self.assertFalse(old.exists())
        for path in (legacy, current, newer, prerelease):
            self.assertTrue(path.exists())

    def test_lock_keeps_running_version(self):
        old = self.payload('0.1.0')
        with (self.root / '.locks' / '0.1.0').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            cleanup.cleanup(self.root, '0.2.0')
            self.assertTrue(old.exists())
        cleanup.cleanup(self.root, '0.2.0')
        self.assertFalse(old.exists())
        self.assertTrue((self.root / '.locks' / '0.1.0').exists())

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock"), "Linux flock required")
    def test_generated_launcher_keeps_lock_while_running(self):
        old = self.payload('0.1.0')
        (old / 'bin').mkdir()
        shutil.copy(shutil.which('sleep'), old / 'bin' / 'codex')
        installer = (helper.parent / 'install-native-codex-cli').read_text()
        functions = (installer[installer.index('shell_quote() {'):installer.index('json_field() {')]
                     + installer[installer.index('write_launcher() {'):installer.index('backup_existing_launcher() {')])
        source = self.root / 'functions.sh'
        source.write_text(functions)
        launcher = self.root / 'launcher'
        lock = self.root / '.locks' / '0.1.0'
        subprocess.run(['bash', '-c', 'source "$1"; write_launcher "$2" "$3" bin/codex 0 "$4"',
                        'bash', str(source), str(launcher), str(old), str(lock)], check=True)
        process = subprocess.Popen([str(launcher), '30'], start_new_session=True)
        try:
            for _ in range(100):
                with lock.open('a') as fd:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        break
                time.sleep(0.01)
            else:
                self.fail('launcher did not acquire its lock')
            cleanup.cleanup(self.root, '0.2.0')
            self.assertTrue(old.exists())
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
        cleanup.cleanup(self.root, '0.2.0')
        self.assertFalse(old.exists())

    def test_symlink_is_preserved(self):
        path = self.root / '0.1.0'
        path.symlink_to('/tmp', target_is_directory=True)
        cleanup.cleanup(self.root, '0.2.0')
        self.assertTrue(path.is_symlink())


if __name__ == '__main__':
    unittest.main()
