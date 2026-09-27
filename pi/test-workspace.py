"""Regression tests for workspace validation and cleanup bookkeeping."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("controller", ROOT / "controller.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class WorkspaceValidationTests(unittest.TestCase):
    def trial(self, repo):
        args = SimpleNamespace(repo=repo, timeout=30, agent_only=True)
        with patch.object(controller, "docker"):
            return controller.Trial(args)

    def test_non_git_workspace_fails_before_archive_or_docker_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "project"
            repo.mkdir()
            trial = self.trial(repo)
            with patch.object(controller, "capture") as capture, \
                    patch.object(controller, "docker") as docker:
                with self.assertRaisesRegex(ValueError, "committed HEAD"):
                    trial.prepare()
            capture.assert_not_called()
            docker.assert_not_called()

    def test_unborn_git_workspace_is_rejected_before_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "project"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            trial = self.trial(repo)
            with patch.object(controller, "capture") as capture:
                with self.assertRaisesRegex(ValueError, "committed HEAD"):
                    trial.prepare()
            capture.assert_not_called()

    def test_readonly_workspace_skips_archive_and_uses_readonly_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "project"
            repo.mkdir()
            args = SimpleNamespace(repo=repo, timeout=30, agent_only=True,
                                   workspace_mode="ro", backend="exl3")
            with patch.object(controller, "docker"):
                trial = controller.Trial(args)
            with patch.object(controller, "capture") as capture, \
                    patch.object(controller, "docker",
                                 return_value=SimpleNamespace(stdout=b"")) as docker:
                trial.prepare()
            capture.assert_not_called()
            agent_calls = [call.args for call in docker.call_args_list
                           if trial.agent in call.args]
            self.assertTrue(agent_calls)
            flattened = agent_calls[0]
            self.assertIn(f"type=bind,src={repo},dst=/workspace,readonly", flattened)
            self.assertNotIn("/workspace:rw,nosuid,nodev,size=512m,nr_inodes=65536,uid=1000,gid=1000",
                             flattened)


class CleanupTests(unittest.TestCase):
    def trial(self):
        with patch.object(controller, "docker"):
            return controller.Trial(SimpleNamespace(repo=Path("."), timeout=30, agent_only=True))

    def test_cleanup_does_not_remove_volume_that_was_not_created(self):
        trial = self.trial()
        trial.containers = []
        with patch.object(controller, "docker") as docker:
            docker.return_value = SimpleNamespace(stdout=b"")
            self.assertEqual(trial.cleanup(), [])
        self.assertFalse(any(call.args[:2] == ("volume", "rm") for call in docker.call_args_list))

    def test_cleanup_preserves_container_and_volume_removal_failures(self):
        trial = self.trial()
        trial.containers = ["agent"]
        trial.volume_created = True

        def fail_removals(*args, **kwargs):
            if args[:2] == ("rm", "-f") or args[:3] == ("volume", "rm", trial.volume):
                raise subprocess.CalledProcessError(1, args)
            return SimpleNamespace(stdout=b"")

        with patch.object(controller, "docker", side_effect=fail_removals) as docker:
            errors = trial.cleanup()
        self.assertEqual(len(errors), 2)
        self.assertEqual(sum("returned non-zero exit status 1" in error for error in errors), 2)
        self.assertTrue(any(call.args[:2] == ("volume", "rm") for call in docker.call_args_list))


if __name__ == "__main__":
    unittest.main()
