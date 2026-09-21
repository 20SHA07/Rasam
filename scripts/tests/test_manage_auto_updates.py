"""Verify task definitions and registration decisions without creating OS tasks."""

from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "manage_auto_updates.py"
spec = importlib.util.spec_from_file_location("manage_auto_updates", SCRIPT)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path("C:/Users/Example/OneDrive - Example/Sites/Rasam")
        self.sid = "S-1-5-21-123-456-789-1001"
        self.python = Path("C:/Program Files/Python311/pythonw.exe")
        self.log = Path("C:/Users/Example/AppData/Local/Rasam/updates.log")
        self.config = {
            "version": 1, "repo": str(self.repo), "sid": self.sid,
            "python": str(self.python), "log": str(self.log),
        }
        self.xml = manager.build_task_xml(self.repo, self.sid, self.python,
                                          self.log, datetime(2026, 9, 21, 12, 0))

    def test_interactive_least_privilege_and_two_triggers(self):
        root = ET.fromstring(self.xml)
        find = lambda p: root.findtext(p, namespaces=manager.NS)
        self.assertEqual(find("t:Principals/t:Principal/t:UserId"), self.sid)
        self.assertEqual(find("t:Principals/t:Principal/t:LogonType"), "InteractiveToken")
        self.assertEqual(find("t:Principals/t:Principal/t:RunLevel"), "LeastPrivilege")
        self.assertEqual(find("t:Triggers/t:LogonTrigger/t:UserId"), self.sid)
        self.assertEqual(find("t:Triggers/t:TimeTrigger/t:StartBoundary"), "2026-09-21T12:01:00")
        self.assertEqual(find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval"), "PT5M")
        self.assertIsNone(find("t:Triggers/t:TimeTrigger/t:Repetition/t:Duration"))
        self.assertEqual(find("t:Settings/t:MultipleInstancesPolicy"), "IgnoreNew")
        self.assertEqual(find("t:Settings/t:ExecutionTimeLimit"), "PT3M")
        self.assertEqual(find("t:Settings/t:WakeToRun"), "false")

    def test_windows_arguments_preserve_spaces_and_escape_xml(self):
        root = ET.fromstring(self.xml)
        self.assertEqual(root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=manager.NS),
                         subprocess.list2cmdline([
                             str(self.repo / "scripts" / "auto_update.py"), "--repo",
                             str(self.repo), "--log", str(self.log)]))
        special = Path("C:/Sites/A&B <Rasam>")
        encoded = manager.build_task_xml(special, self.sid, self.python, self.log)
        decoded = ET.fromstring(encoded)
        self.assertEqual(decoded.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=manager.NS), str(special))

    def test_owned_task_is_accepted(self):
        manager.assert_owned_task(self.xml, self.repo, self.sid, self.config)

    def test_unrelated_tasks_or_configuration_are_rejected(self):
        for xml, config in [
            (self.xml.replace("Rasam GitHub updater v1", "Someone else's task"), self.config),
            (self.xml.replace("LeastPrivilege", "HighestAvailable"), self.config),
            (self.xml.replace("--repo", "--delete"), self.config),
            (self.xml.replace(str(self.python), "C:/other.exe"), self.config),
            (self.xml, {}),
            (self.xml, {**self.config, "sid": "S-1-5-18"}),
            ("broken XML", self.config),
        ]:
            with self.subTest(xml=xml[:40], config=config):
                with self.assertRaises(manager.SetupError):
                    manager.assert_owned_task(xml, self.repo, self.sid, config)

    def test_additional_action_is_rejected(self):
        xml = self.xml.replace("</Actions>", "<Exec><Command>other.exe</Command></Exec></Actions>")
        with self.assertRaises(manager.SetupError):
            manager.assert_owned_task(xml, self.repo, self.sid, self.config)

    def test_identity_distinguishes_accounts_and_clones(self):
        current = manager.task_identity(self.repo, self.sid)
        self.assertNotEqual(current, manager.task_identity(self.repo, "S-1-5-18"))
        self.assertNotEqual(current, manager.task_identity(Path("C:/other"), self.sid))
        self.assertEqual(current, manager.task_identity(Path(str(self.repo).upper()), self.sid))

    def test_windows_xml_output_decodes_with_or_without_bom(self):
        for encoding in ["utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "utf-8"]:
            with self.subTest(encoding=encoding):
                decoded = manager.decode_output(self.xml.encode(encoding))
                manager.assert_owned_task(decoded, self.repo, self.sid, self.config)

    def test_command_output_is_decoded_from_bytes(self):
        raw = subprocess.CompletedProcess([], 0, self.xml.encode("utf-16"), b"")
        with patch.object(manager.subprocess, "run", return_value=raw) as run:
            result = manager.run_command(["schtasks.exe", "/Query", "/XML"])
        self.assertEqual(result.stdout, self.xml)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", run.call_args.kwargs)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "OneDrive - Example" / "Sites" / "Rasam"
        self.repo.mkdir(parents=True)
        self.data = self.root / "local-data"
        self.sid = "S-1-5-21-123-456-789-1001"
        self.xml = None
        self.calls = []
        self.denied = False

    def command(self, args, **kwargs):
        self.calls.append(args)
        action = args[1]
        if action == "/Query":
            return subprocess.CompletedProcess(args, 0 if self.xml is not None else 1,
                                               self.xml or "", "")
        if action == "/Create":
            if self.denied:
                return subprocess.CompletedProcess(args, 1, "", "Access is denied.")
            self.xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
        if action == "/Delete":
            self.xml = None
        return subprocess.CompletedProcess(args, 0, "", "")

    def invoke(self, action):
        with patch.object(manager.sys, "platform", "win32"), \
             patch.object(manager, "current_user_sid", return_value=self.sid), \
             patch.object(manager, "system_tool", return_value="schtasks.exe"), \
             patch.object(manager, "validate_repo"), \
             patch.object(manager, "run_command", side_effect=self.command), \
             patch.dict(os.environ, {"LOCALAPPDATA": str(self.data)}), \
             patch("builtins.print"):
            return manager.manage(action, self.repo)

    def config_path(self):
        identity = manager.task_identity(self.repo, self.sid)
        return self.data / "Rasam" / "auto-updates" / identity / "task.json"

    def test_new_registration_does_not_force_overwrite(self):
        self.assertEqual(self.invoke("enable"), 0)
        creation = next(c for c in self.calls if c[1] == "/Create")
        self.assertNotIn("/F", creation)
        self.assertTrue(any(c[1] == "/Run" for c in self.calls))
        config = json.loads(self.config_path().read_text())
        self.assertEqual(config["repo"], str(self.repo))
        self.assertFalse(str(config["log"]).startswith(str(self.repo)))
        self.assertFalse(list(self.data.rglob("task.xml")))

    def test_repeat_enable_can_update_only_owned_task(self):
        self.invoke("enable")
        self.calls.clear()
        self.invoke("enable")
        creation = next(c for c in self.calls if c[1] == "/Create")
        self.assertIn("/F", creation)

    def test_unrelated_task_is_not_overwritten_or_removed(self):
        self.xml = "<Task><Description>Other app</Description></Task>"
        for action in ["enable", "disable"]:
            self.calls.clear()
            with self.assertRaises(manager.SetupError):
                self.invoke(action)
            self.assertFalse(any(c[1] in ("/Create", "/Delete") for c in self.calls))

    def test_disable_removes_matching_task_and_preserves_log(self):
        self.invoke("enable")
        config = json.loads(self.config_path().read_text())
        log = Path(config["log"])
        log.write_text("previous update result")
        self.invoke("disable")
        self.assertIsNone(self.xml)
        self.assertFalse(self.config_path().exists())
        self.assertEqual(log.read_text(), "previous update result")

    def test_failed_registration_is_reported_without_config(self):
        self.denied = True
        with self.assertRaisesRegex(manager.SetupError, "Windows did not allow"):
            self.invoke("enable")
        self.assertFalse(self.config_path().exists())
        self.assertFalse(any(c[1] == "/Run" for c in self.calls))

    def test_missing_task_with_saved_config_does_not_delete_config(self):
        self.invoke("enable")
        self.xml = None
        with self.assertRaisesRegex(manager.SetupError, "Could not inspect"):
            self.invoke("disable")
        self.assertTrue(self.config_path().exists())

    def test_pythonw_is_used_when_available(self):
        python_dir = self.repo / "workbench" / ".venv" / "Scripts"
        python_dir.mkdir(parents=True)
        (python_dir / "python.exe").touch()
        (python_dir / "pythonw.exe").touch()
        self.invoke("enable")
        config = json.loads(self.config_path().read_text())
        self.assertEqual(config["python"], str(python_dir / "pythonw.exe"))


class RepositoryChecks(unittest.TestCase):
    def test_only_single_https_origin_on_main_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp).resolve()
            (repo / "scripts").mkdir()
            (repo / "scripts" / "auto_update.py").touch()
            cases = [
                ("main", "https://github.com/20SHA07/Rasam.git", True),
                ("main", "https://github.com/20SHA07/Rasam", True),
                ("feature", "https://github.com/20SHA07/Rasam.git", False),
                ("main", "git@github.com:20SHA07/Rasam.git", False),
                ("main", "https://github.com/20SHA07/Rasam.git\nhttps://example.com/other", False),
            ]
            for branch, remote, accepted in cases:
                results = [subprocess.CompletedProcess([], 0, value + "\n", "")
                           for value in [str(repo), branch, remote]]
                with self.subTest(branch=branch, remote=remote), \
                     patch.object(manager.shutil, "which", return_value="git"), \
                     patch.object(manager, "run_command", side_effect=results) as run:
                    if accepted:
                        manager.validate_repo(repo)
                        self.assertEqual(run.call_args.args[0][-4:], ["remote", "get-url", "--all", "origin"])
                    else:
                        with self.assertRaises(manager.SetupError):
                            manager.validate_repo(repo)


if __name__ == "__main__":
    unittest.main()
