#!/usr/bin/env python3
"""Install or remove Rasam's current-user Windows GitHub update task."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
NS = {"t": TASK_NS}
ET.register_namespace("", TASK_NS)
ORIGINS = {
    "https://github.com/20SHA07/Rasam",
    "https://github.com/20SHA07/Rasam.git",
}


class SetupError(Exception):
    pass


def decode_output(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    # schtasks XML can use UTF-16LE even without a byte-order mark.
    if data and data.count(b"\x00") > len(data) // 5:
        encoding = "utf-16-be" if data.startswith(b"\x00") else "utf-16-le"
        return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), errors="replace")


def run_command(args: list[str], *, timeout: int = 30):
    result = subprocess.run(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout,
        check=False,
    )
    return subprocess.CompletedProcess(args, result.returncode,
                                     decode_output(result.stdout), decode_output(result.stderr))


def system_tool(name: str) -> str:
    root = os.environ.get("SystemRoot")
    if not root:
        raise SetupError("Windows SystemRoot is unavailable.")
    executable = Path(root) / "System32" / name
    if not executable.is_file():
        raise SetupError(f"Windows tool {name} was not found.")
    return str(executable)


def current_user_sid() -> str:
    result = run_command([system_tool("whoami.exe"), "/user", "/fo", "csv", "/nh"])
    if result.returncode == 0:
        for row in csv.reader(io.StringIO(result.stdout)):
            if row and re.fullmatch(r"S-1-\d+(?:-\d+)+", row[-1].strip()):
                return row[-1].strip()
    raise SetupError("Could not identify the signed-in Windows account.")


def task_identity(repo: Path, sid: str) -> str:
    identity = str(repo).replace("/", "\\").casefold() + "\n" + sid
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def task_description(repo: Path, sid: str) -> str:
    return f"Rasam GitHub updater v1; user={sid}; repo={repo}"


def task_arguments(repo: Path, log_path: Path) -> str:
    return subprocess.list2cmdline([
        str(repo / "scripts" / "auto_update.py"),
        "--repo", str(repo), "--log", str(log_path),
    ])


def build_task_xml(repo: Path, sid: str, python_path: Path,
                   log_path: Path, now: datetime | None = None) -> str:
    def add(parent, name, value=None, **attributes):
        child = ET.SubElement(parent, f"{{{TASK_NS}}}{name}", attributes)
        if value is not None:
            child.text = str(value)
        return child

    task = ET.Element(f"{{{TASK_NS}}}Task", {"version": "1.2"})
    registration = add(task, "RegistrationInfo")
    add(registration, "Description", task_description(repo, sid))
    triggers = add(task, "Triggers")
    timer = add(triggers, "TimeTrigger")
    repetition = add(timer, "Repetition")
    add(repetition, "Interval", "PT5M")
    # Omitted Duration repeats indefinitely, while the account is signed in.
    add(repetition, "StopAtDurationEnd", "false")
    start = (now or datetime.now()).replace(microsecond=0) + timedelta(minutes=1)
    add(timer, "StartBoundary", start.isoformat())
    add(timer, "Enabled", "true")
    logon = add(triggers, "LogonTrigger")
    add(logon, "Enabled", "true")
    add(logon, "UserId", sid)
    principals = add(task, "Principals")
    principal = add(principals, "Principal", id="RasamUpdater")
    add(principal, "UserId", sid)
    add(principal, "LogonType", "InteractiveToken")
    add(principal, "RunLevel", "LeastPrivilege")
    settings = add(task, "Settings")
    for key, value in [
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("RunOnlyIfNetworkAvailable", "false"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT3M"),
    ]:
        add(settings, key, value)
    actions = add(task, "Actions", Context="RasamUpdater")
    execute = add(actions, "Exec")
    add(execute, "Command", str(python_path))
    add(execute, "Arguments", task_arguments(repo, log_path))
    add(execute, "WorkingDirectory", str(repo))
    return ET.tostring(task, encoding="unicode", xml_declaration=False)


def assert_owned_task(xml: str, repo: Path, sid: str, config: dict) -> None:
    """Require our exact marker, user and previously recorded action."""
    try:
        root = ET.fromstring(xml)
        principals = root.findall("t:Principals/t:Principal", NS)
        actions = root.findall("t:Actions/*", NS)
        expected = {
            "t:RegistrationInfo/t:Description": task_description(repo, sid),
            "t:Principals/t:Principal/t:UserId": sid,
            "t:Principals/t:Principal/t:LogonType": "InteractiveToken",
            "t:Principals/t:Principal/t:RunLevel": "LeastPrivilege",
            "t:Actions/t:Exec/t:Command": config["python"],
            "t:Actions/t:Exec/t:Arguments": task_arguments(repo, Path(config["log"])),
            "t:Actions/t:Exec/t:WorkingDirectory": str(repo),
        }
        owned = (
            root.tag == f"{{{TASK_NS}}}Task"
            and config.get("repo") == str(repo)
            and config.get("sid") == sid
            and config.get("version") == 1
            and len(principals) == 1 and len(actions) == 1
            and all(root.findtext(key, default="", namespaces=NS) == value
                    for key, value in expected.items())
        )
    except (ET.ParseError, KeyError, TypeError, ValueError):
        owned = False
    if not owned:
        raise SetupError(
            "A task with this name exists, but its ownership or action does not match "
            "this Rasam folder. It was left unchanged."
        )


def validate_repo(repo: Path) -> None:
    git = shutil.which("git")
    if not git:
        raise SetupError("Install Git for Windows, then open this launcher again.")
    if not (repo / "scripts" / "auto_update.py").is_file():
        raise SetupError("Rasam's updater is missing. Pull the latest main branch first.")

    def git_output(*arguments):
        result = run_command([git, "-C", str(repo), *arguments])
        if result.returncode != 0:
            raise SetupError("This folder must be a Git clone of 20SHA07/Rasam.")
        return result.stdout.strip()

    actual_root = Path(git_output("rev-parse", "--show-toplevel")).resolve()
    if os.path.normcase(str(actual_root)) != os.path.normcase(str(repo)):
        raise SetupError("Run setup from the root of the Rasam Git clone.")
    if git_output("symbolic-ref", "--short", "HEAD") != "main":
        raise SetupError("Switch this Rasam clone to its main branch before enabling updates.")
    if git_output("remote", "get-url", "--all", "origin") not in ORIGINS:
        raise SetupError("The origin remote must be the public 20SHA07/Rasam GitHub repository.")


def read_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError("The saved updater configuration could not be read; no task was changed.") from exc
    if not isinstance(config, dict):
        raise SetupError("The saved updater configuration is invalid; no task was changed.")
    return config


def manage(action: str, repo: Path) -> int:
    if sys.platform != "win32":
        raise SetupError("This automatic-update installer runs on Windows only.")
    repo = repo.resolve()
    sid = current_user_sid()
    identity = task_identity(repo, sid)
    task_name = f"Rasam-GitHub-Update-{identity}"
    local_data = os.environ.get("LOCALAPPDATA")
    if not local_data:
        raise SetupError("Windows LOCALAPPDATA is unavailable.")
    task_dir = Path(local_data) / "Rasam" / "auto-updates" / identity
    config_path = task_dir / "task.json"
    log_path = task_dir / "updates.log"
    config = read_config(config_path)
    scheduler = system_tool("schtasks.exe")
    query = run_command([scheduler, "/Query", "/TN", task_name, "/XML"])
    existing = query.stdout if query.returncode == 0 else None
    if existing is not None:
        assert_owned_task(existing, repo, sid, config or {})
    elif config is not None and (config.get("repo") != str(repo) or config.get("sid") != sid):
        raise SetupError("Saved configuration belongs to a different installation; it was left unchanged.")

    if action == "disable":
        if existing is None:
            if config is not None:
                raise SetupError(
                    f"Could not inspect {task_name}. It may already be removed, or Windows denied access. "
                    "No task or saved configuration was changed."
                )
            print("No automatic-update task was found for this Rasam folder.")
            return 0
        result = run_command([scheduler, "/Delete", "/TN", task_name, "/F"])
        if result.returncode != 0:
            raise SetupError("Windows could not remove Rasam's update task. Check Task Scheduler.")
        config_path.unlink(missing_ok=True)
        print("Automatic updates disabled. Your Rasam files and update log are unchanged.")
        return 0

    validate_repo(repo)
    python_path = repo / "workbench" / ".venv" / "Scripts" / "python.exe"
    if not python_path.is_file():
        python_path = Path(sys.executable).resolve()
    windowless = python_path.with_name("pythonw.exe")
    if windowless.is_file():
        python_path = windowless
    new_config = {
        "version": 1, "repo": str(repo), "sid": sid,
        "task_name": task_name, "python": str(python_path), "log": str(log_path),
    }
    xml = build_task_xml(repo, sid, python_path, log_path)
    task_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="setup-", dir=task_dir) as temp_dir:
        xml_path = Path(temp_dir) / "task.xml"
        xml_path.write_text(xml, encoding="utf-16")
        command = [scheduler, "/Create", "/TN", task_name, "/XML", str(xml_path)]
        if existing is not None:
            command.append("/F")
        result = run_command(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SetupError(
            "Windows did not allow the update task to be registered. "
            "Task Scheduler may be restricted on this computer. No administrator or "
            "PowerShell policy changes were made. You can still use git pull --ff-only."
            + (f"\nWindows reported: {detail}" if detail else "")
        )
    # Persist ownership immediately after a successful registration so removal is possible.
    temp_config = config_path.with_suffix(".json.tmp")
    temp_config.write_text(json.dumps(new_config, indent=2) + "\n", encoding="utf-8")
    temp_config.replace(config_path)
    verification = run_command([scheduler, "/Query", "/TN", task_name, "/XML"])
    if verification.returncode != 0:
        raise SetupError(f"The task was registered but could not be verified. Check Task Scheduler: {task_name}")
    assert_owned_task(verification.stdout, repo, sid, new_config)
    print("Automatic GitHub updates enabled for this Rasam folder.")
    print("Checks run every 5 minutes and at sign-in while you are signed in and the PC is awake.")
    print("Updates require internet. Local edits, unpushed commits or conflicting history pause updates.")
    print("Restart Rasam after an update to load the new app code.")
    print(f"Task: {task_name}")
    print(f"Update log: {log_path}")
    initial_run = run_command([scheduler, "/Run", "/TN", task_name])
    if initial_run.returncode == 0:
        print("The first background check has been requested. See the log for its result.")
    else:
        print("An immediate check could not start. The first scheduled check is due in about a minute.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enable", "disable"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        return manage(args.action, args.repo)
    except (SetupError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Rasam auto-update setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
