#!/usr/bin/env python3
"""Safely pull published Rasam updates into an otherwise untouched checkout.

This is a one-shot command intended to be called by Windows Task Scheduler.
It never pushes, commits, stashes, resets, or resolves a conflict.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile


ALLOWED_ORIGINS = (
    "https://github.com/20SHA07/Rasam.git",
    "https://github.com/20SHA07/Rasam",
)
MAX_LOG_BYTES = 128 * 1024


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message: str
    exit_code: int = 0


class GitFailure(Exception):
    """An error whose underlying output must not enter the updater log."""


class Git:
    def __init__(self, repo: Path, hooks_dir: str):
        self.repo = repo
        self.hooks_dir = hooks_dir

    def run(self, *args: str, timeout: int = 15, check: bool = True):
        env = os.environ.copy()
        env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        })
        # Do not inherit shell overrides that could redirect -C to another repo.
        for name in (
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        ):
            env.pop(name, None)
        command = [
            "git", "-C", str(self.repo),
            "-c", f"core.hooksPath={self.hooks_dir}",
            "-c", "submodule.recurse=false",
            "-c", "credential.helper=",
            "-c", "credential.interactive=false",
            "-c", "core.askPass=",
            *args,
        ]
        try:
            result = subprocess.run(
                command, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                stdin=subprocess.DEVNULL, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitFailure() from exc
        if check and result.returncode:
            raise GitFailure()
        return result

    def text(self, *args: str) -> str:
        return self.run(*args).stdout.strip()


def _dirty(git: Git) -> bool:
    return bool(git.text(
        "status", "--porcelain=v1", "--untracked-files=all",
        "--ignore-submodules=none",
    ))


def _operation_in_progress(git: Git) -> bool:
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        location = Path(git.text("rev-parse", "--git-path", name))
        if not location.is_absolute():
            location = git.repo / location
        if location.exists():
            return True
    return False


def _update(git: Git, allowed_origins: tuple[str, ...]) -> UpdateResult:
    checkout = git.run("rev-parse", "--show-toplevel", check=False)
    if checkout.returncode or Path(checkout.stdout.strip()).resolve() != git.repo:
        return UpdateResult("skipped-checkout", "Skipped: the specified folder is not the root of a Git checkout.")
    if git.text("rev-parse", "--is-bare-repository") != "false":
        return UpdateResult("skipped-checkout", "Skipped: a working checkout is required.")
    branch = git.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode or branch.stdout.strip() != "main":
        return UpdateResult("skipped-branch", "Skipped: this checkout is not on main.")
    remote = git.run("remote", "get-url", "--all", "origin", check=False)
    urls = remote.stdout.splitlines()
    if remote.returncode or len(urls) != 1 or urls[0] not in allowed_origins:
        return UpdateResult("skipped-origin", "Skipped: origin does not match the public Rasam repository.")
    if _operation_in_progress(git):
        return UpdateResult("skipped-operation", "Skipped: another Git operation is in progress.")
    if _dirty(git):
        return UpdateResult("skipped-dirty", "Skipped: local edits or untracked files need your attention.")

    original_head = git.text("rev-parse", "HEAD")
    try:
        git.run(
            "fetch", "--no-tags", "--no-recurse-submodules", "origin",
            "+refs/heads/main:refs/remotes/origin/main", timeout=60,
        )
    except GitFailure:
        return UpdateResult("fetch-failed", "Could not fetch GitHub updates; the next scheduled check will retry.", 1)

    # Fetch can take time. Do not apply its result if someone edited or switched.
    branch = git.run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode or branch.stdout.strip() != "main" or git.text("rev-parse", "HEAD") != original_head:
        return UpdateResult("skipped-changed", "Skipped: the checkout changed while checking for updates.")
    if _operation_in_progress(git) or _dirty(git):
        return UpdateResult("skipped-dirty", "Skipped: local edits or another Git operation appeared during the check.")
    target = git.text("rev-parse", "refs/remotes/origin/main")
    if target == original_head:
        return UpdateResult("up-to-date", "Rasam is already up to date.")
    ancestor = git.run("merge-base", "--is-ancestor", original_head, target, check=False)
    if ancestor.returncode == 1:
        return UpdateResult("skipped-history", "Skipped: local commits or changed GitHub history need your attention.")
    if ancestor.returncode:
        raise GitFailure()
    # Use the exact inspected commit and never create a merge commit.
    merged = git.run(
        "merge", "--ff-only", "--no-edit", "--no-autostash",
        "--no-overwrite-ignore", target, timeout=30, check=False,
    )
    if merged.returncode:
        return UpdateResult("update-failed", "Git could not apply the update safely; please inspect the checkout.", 1)
    return UpdateResult("updated", "Rasam was updated from GitHub. Restart the app to use the changes.")


def update_repository(repo: Path, *, _allowed_origins: tuple[str, ...] = ALLOWED_ORIGINS) -> UpdateResult:
    """Run once; the private origin override only supports isolated local tests."""
    try:
        resolved = repo.expanduser().resolve()
        if not resolved.is_dir():
            return UpdateResult("skipped-checkout", "Skipped: the checkout folder does not exist.")
        # An empty, temporary hooks directory prevents post-merge code execution.
        with tempfile.TemporaryDirectory(prefix="rasam-update-hooks-") as hooks_dir:
            return _update(Git(resolved, hooks_dir), _allowed_origins)
    except (GitFailure, OSError, ValueError):
        return UpdateResult("git-failed", "Git could not check this folder; confirm Git is installed and the checkout is accessible.", 1)


def append_log(path: Path, result: UpdateResult) -> None:
    """Bound the log and never include Git output, filenames, or credentials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = f"{stamp} [{result.status}] {result.message}\n".encode("utf-8")
    # Retain recent complete lines, with a hard size cap even after many runs.
    old = b""
    if path.exists():
        with path.open("rb") as source:
            source.seek(max(0, path.stat().st_size - MAX_LOG_BYTES // 2))
            old = source.read(MAX_LOG_BYTES // 2)
        if old and path.stat().st_size > MAX_LOG_BYTES // 2:
            old = old.partition(b"\n")[2]
    if len(old) + len(entry) > MAX_LOG_BYTES:
        old = b""
    path.write_bytes(old + entry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--log", type=Path, help="Optional log path outside the checkout.")
    args = parser.parse_args(argv)
    if args.log:
        try:
            args.log.expanduser().resolve().relative_to(args.repo.expanduser().resolve())
        except ValueError:
            pass
        else:
            print("Log path must be outside the checkout so it cannot create local edits.")
            return 1
    result = update_repository(args.repo)
    print(f"[{result.status}] {result.message}")
    if args.log:
        try:
            append_log(args.log.expanduser().resolve(), result)
        except OSError:
            print("Could not write the updater log.")
            return 1
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
