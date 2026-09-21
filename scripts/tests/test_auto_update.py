"""Real local Git repositories verify that background pulls preserve user work."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "auto_update.py"
spec = importlib.util.spec_from_file_location("rasam_auto_update", MODULE_PATH)
auto_update = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auto_update
spec.loader.exec_module(auto_update)


def git(folder, *args):
    return subprocess.run(
        ["git", "-C", str(folder), "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    ).stdout.strip()


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rasam update test ")
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.source = self.root / "publisher"
        self.repo = self.root / "Sites" / "Rasam"
        git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        git(self.root, "clone", str(self.remote), str(self.source))
        for folder in (self.source,):
            git(folder, "config", "user.email", "test@example.invalid")
            git(folder, "config", "user.name", "Rasam test")
        (self.source / "app.txt").write_text("initial app\n")
        git(self.source, "add", "app.txt")
        git(self.source, "commit", "-m", "Initial")
        git(self.source, "push", "origin", "main")
        git(self.root, "clone", str(self.remote), str(self.repo))
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Rasam test")
        self.original_head = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def publish(self):
        (self.source / "app.txt").write_text("new published app\n")
        git(self.source, "add", "app.txt")
        git(self.source, "commit", "-m", "Published update")
        git(self.source, "push", "origin", "main")
        return git(self.source, "rev-parse", "HEAD")

    def run_update(self, repo=None):
        return auto_update.update_repository(repo or self.repo, _allowed_origins=(str(self.remote),))

    def assert_untouched(self):
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.original_head)

    def test_clean_checkout_fast_forwards(self):
        target = self.publish()
        result = self.run_update()
        self.assertEqual(result.status, "updated")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), target)
        self.assertEqual((self.repo / "app.txt").read_text(), "new published app\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_current_checkout_has_no_new_commit(self):
        result = self.run_update()
        self.assertEqual(result.status, "up-to-date")
        self.assert_untouched()

    def test_tracked_edits_are_preserved(self):
        self.publish()
        (self.repo / "app.txt").write_text("my unfinished work\n")
        self.assertEqual(self.run_update().status, "skipped-dirty")
        self.assertEqual((self.repo / "app.txt").read_text(), "my unfinished work\n")
        self.assert_untouched()

    def test_untracked_file_is_preserved_and_blocks_update(self):
        self.publish()
        (self.repo / "private invoice.txt").write_text("must stay local\n")
        result = self.run_update()
        self.assertEqual(result.status, "skipped-dirty")
        self.assertNotIn("private invoice", result.message)
        self.assertEqual((self.repo / "private invoice.txt").read_text(), "must stay local\n")
        self.assert_untouched()

    def test_staged_edit_is_preserved(self):
        self.publish()
        (self.repo / "app.txt").write_text("staged work\n")
        git(self.repo, "add", "app.txt")
        self.assertEqual(self.run_update().status, "skipped-dirty")
        self.assertIn("staged work", git(self.repo, "show", ":app.txt"))
        self.assert_untouched()

    def test_incoming_file_cannot_overwrite_ignored_local_file(self):
        (self.repo / ".git" / "info" / "exclude").write_text("private.txt\n")
        (self.repo / "private.txt").write_text("local private data\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        (self.source / "private.txt").write_text("published file with same name\n")
        git(self.source, "add", "private.txt")
        git(self.source, "commit", "-m", "Add colliding file")
        git(self.source, "push", "origin", "main")
        self.assertEqual(self.run_update().status, "update-failed")
        self.assertEqual((self.repo / "private.txt").read_text(), "local private data\n")
        self.assert_untouched()

    def test_local_commit_is_never_pushed_or_removed(self):
        (self.repo / "local.txt").write_text("my commit\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-m", "Local work")
        local_head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.run_update().status, "skipped-history")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local_head)
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.original_head)

    def test_diverged_commits_are_never_merged(self):
        target = self.publish()
        (self.repo / "local.txt").write_text("my commit\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-m", "Local work")
        local_head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.run_update().status, "skipped-history")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local_head)
        self.assertEqual(git(self.remote, "rev-parse", "main"), target)

    def test_other_branch_is_not_changed(self):
        self.publish()
        git(self.repo, "checkout", "-b", "my-work")
        self.assertEqual(self.run_update().status, "skipped-branch")
        self.assertEqual(git(self.repo, "branch", "--show-current"), "my-work")
        self.assert_untouched()

    def test_detached_head_is_not_changed(self):
        self.publish()
        git(self.repo, "checkout", "--detach")
        self.assertEqual(self.run_update().status, "skipped-branch")
        self.assert_untouched()

    def test_nested_directory_does_not_update_parent_checkout(self):
        self.publish()
        nested = self.repo / "nested"
        nested.mkdir()
        self.assertEqual(self.run_update(nested).status, "skipped-checkout")
        self.assert_untouched()

    def test_missing_directory_is_skipped(self):
        self.assertEqual(self.run_update(self.root / "missing").status, "skipped-checkout")

    def test_origin_mismatch_does_not_contact_remote(self):
        git(self.repo, "remote", "set-url", "origin", "https://secret-token@example.invalid/private.git")
        result = self.run_update()
        self.assertEqual(result.status, "skipped-origin")
        self.assertNotIn("secret-token", result.message)
        self.assert_untouched()

    def test_production_origin_allowlist_rejects_local_remote(self):
        self.assertEqual(auto_update.update_repository(self.repo).status, "skipped-origin")
        self.assert_untouched()

    def test_failed_fetch_preserves_checkout(self):
        self.remote.rename(self.root / "offline.git")
        result = self.run_update()
        self.assertEqual(result.status, "fetch-failed")
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn(str(self.remote), result.message)
        self.assert_untouched()
        self.assertEqual((self.repo / "app.txt").read_text(), "initial app\n")

    def test_edits_during_fetch_are_preserved(self):
        self.publish()
        original_run = auto_update.Git.run

        def edit_after_fetch(instance, *args, **kwargs):
            result = original_run(instance, *args, **kwargs)
            if args[0] == "fetch":
                (self.repo / "app.txt").write_text("work during fetch\n")
            return result

        with patch.object(auto_update.Git, "run", edit_after_fetch):
            self.assertEqual(self.run_update().status, "skipped-dirty")
        self.assertEqual((self.repo / "app.txt").read_text(), "work during fetch\n")
        self.assert_untouched()

    def test_branch_switch_during_fetch_is_preserved(self):
        self.publish()
        original_run = auto_update.Git.run

        def switch_after_fetch(instance, *args, **kwargs):
            result = original_run(instance, *args, **kwargs)
            if args[0] == "fetch":
                git(self.repo, "checkout", "-b", "my-work")
            return result

        with patch.object(auto_update.Git, "run", switch_after_fetch):
            self.assertEqual(self.run_update().status, "skipped-changed")
        self.assertEqual(git(self.repo, "branch", "--show-current"), "my-work")
        self.assert_untouched()

    def test_post_merge_hook_does_not_run(self):
        self.publish()
        hook = self.repo / ".git" / "hooks" / "post-merge"
        hook.write_text("#!/bin/sh\nprintf unsafe > hook-ran.txt\n")
        hook.chmod(0o755)
        self.assertEqual(self.run_update().status, "updated")
        self.assertFalse((self.repo / "hook-ran.txt").exists())

    def test_git_operation_in_progress_is_left_alone(self):
        self.publish()
        marker = self.repo / ".git" / "CHERRY_PICK_HEAD"
        marker.write_text(self.original_head + "\n")
        self.assertEqual(self.run_update().status, "skipped-operation")
        self.assertTrue(marker.exists())
        self.assert_untouched()

    def test_network_timeout_is_reported_without_exception_output(self):
        original_run = subprocess.run

        def timeout_fetch(command, **kwargs):
            if "fetch" in command:
                raise subprocess.TimeoutExpired(command, 60, stderr="secret server output")
            return original_run(command, **kwargs)

        with patch.object(auto_update.subprocess, "run", timeout_fetch):
            result = self.run_update()
        self.assertEqual(result.status, "fetch-failed")
        self.assertNotIn("secret", result.message)
        self.assert_untouched()

    def test_git_environment_is_noninteractive_and_not_redirected(self):
        captured = []
        original_run = subprocess.run

        def capture_env(command, **kwargs):
            captured.append(kwargs["env"])
            return original_run(command, **kwargs)

        with patch.dict(os.environ, {"GIT_DIR": "/invalid", "GIT_WORK_TREE": "/invalid"}):
            with patch.object(auto_update.subprocess, "run", capture_env):
                self.assertEqual(self.run_update().status, "up-to-date")
        self.assertTrue(captured)
        for env in captured:
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(env["GCM_INTERACTIVE"], "Never")
            self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
            self.assertNotIn("GIT_DIR", env)
            self.assertNotIn("GIT_WORK_TREE", env)

    def test_log_is_bounded_and_outside_checkout(self):
        log = self.root / "state" / "updates.log"
        log.parent.mkdir()
        log.write_bytes(b"old entry\n" * (auto_update.MAX_LOG_BYTES // 3))
        result = auto_update.UpdateResult("up-to-date", "Rasam is already up to date.")
        auto_update.append_log(log, result)
        self.assertLessEqual(log.stat().st_size, auto_update.MAX_LOG_BYTES)
        self.assertTrue(log.read_text().endswith("[up-to-date] Rasam is already up to date.\n"))
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = auto_update.main(["--repo", str(self.repo), "--log", str(self.repo / "updates.log")])
        self.assertEqual(exit_code, 1)
        self.assertFalse((self.repo / "updates.log").exists())


if __name__ == "__main__":
    unittest.main()
