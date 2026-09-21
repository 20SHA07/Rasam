# Keep your Windows copy updated

Rasam can check GitHub every five minutes and download new changes to your local Git clone. Enable this once on your Windows computer. It is not enabled by downloading the project or by chatting with the assistant.

## Turn it on

1. Open your existing **Rasam** folder. It must be a Git clone of [20SHA07/Rasam](https://github.com/20SHA07/Rasam), on the `main` branch. A downloaded ZIP cannot receive Git updates.
2. If you do not see the installer yet, open a terminal in the Rasam folder and run `git pull --ff-only`.
3. Open **scripts** and double-click **Enable-Auto-Update-Windows.bat**.
4. Wait for **Automatic GitHub updates enabled for this Rasam folder**. The window shows the task name and update-log location.

Python 3.11 and [Git for Windows](https://git-scm.com/downloads/win) must be installed. The installer uses Rasam's Python environment when it exists, otherwise your installed Python. No extra Python packages are needed for updates.

The task checks immediately after setup, every five minutes, and when you sign in. Your Windows account must be signed in, your computer must be awake, and GitHub must be reachable. It does not wake your computer. An offline check leaves the app unchanged and tries again at the next scheduled check.

Updates flow from **GitHub `main` to your local Rasam folder**. The task does not upload files, create commits, or push local changes. When we make and publish changes to GitHub during a chat, your computer can pick them up automatically. This does not make the assistant work continuously between chats.

## While you are working

The updater only fast-forwards a clean `main` branch. Local edits, untracked files, local commits waiting to be pushed, a different branch, or conflicting Git history pause updates. It does not reset files, discard edits, stash your work, or resolve conflicts automatically.

After an update, finish your current invoice work, close Rasam's launcher, and start it again to load the new Python code. The updater does not restart the app or install new dependencies. If a release changes the setup requirements, follow the updated README.

Keep invoices and exports in the ignored data folders listed in `.gitignore`, or outside the Git clone. If you use OneDrive, keep the Rasam folder available on this device so its code and Git files remain accessible.

## Check whether it is working

Open the **updates.log** path printed by the installer. You can also paste `%LOCALAPPDATA%\Rasam\auto-updates` into File Explorer, open this installation's folder, and read **updates.log**. Separate Rasam clones have separate folders and tasks.

The log records each update check and explains skipped updates. If there are local changes, inspect them with `git status` and decide which changes to keep or commit. Automatic updates resume when the clone is clean and can fast-forward to GitHub's `main`.

The Windows task is named **Rasam-GitHub-Update-** followed by an installation identifier. It runs as your current Windows account with ordinary user permissions. It stores no password. Its task configuration and log live under `%LOCALAPPDATA%\Rasam\auto-updates`, outside the repository.

If your organization's Windows settings prevent creating the task, the installer reports that failure. You can still run `git pull --ff-only` manually in the Rasam folder. The installer does not change PowerShell execution policies or request administrator access.

## Turn it off

Double-click **scripts\Disable-Auto-Update-Windows.bat** in the same Rasam folder. It removes only the matching Rasam task for your account and this folder. Your app files and update log remain.

If you move or rename the Rasam folder, disable automatic updates first, then enable them again from its new location. If the old folder was already moved, remove its old **Rasam-GitHub-Update-…** task in Windows Task Scheduler before enabling the new location.

## Technical notes

`scripts/manage_auto_updates.py` registers a Task Scheduler XML definition using Windows `schtasks.exe`. The action runs `scripts/auto_update.py --repo <clone> --log <local log>` with an absolute Python path, using `pythonw.exe` when available to avoid opening a console window. The task permits one running instance and limits each check to three minutes.

The definition uses an interactive user token, least privilege, and an indefinite five-minute repetition. See Microsoft's documentation for [task creation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create), [interactive logon](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-logontype-principaltype-element), and [repetition duration](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-duration-repetitiontype-element).
