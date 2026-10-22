# Windows development installer

The `0.3.0.dev2` installer includes the complete Milestone 3–6 application.
The development branch starts at OpenHands commit
`d6426b54cd3848b43ceae545807c8aa2e0bb9557`, whose baseline has 256 tests.
It retains the HTML ZIP/folder, junction-safety, resource-report and off-thread
storage fixes from `5dde7d5`, `e17fb7f`, `7bad502` and `ce33650`.

## Download and install

Open the successful **Desktop foundation** Actions run for
`dev/windows-installer-fixes`. Download **OpenWrench-development-Windows** from
the run's Artifacts section while signed into GitHub. Extract the artifact ZIP.
It contains `OpenWrench-0.3.0.dev2-setup.exe` and its `.exe.sha256` file.
This is an unsigned development build, not a signed public release.

Check the downloaded installer's SHA-256 in PowerShell:

```powershell
Get-FileHash .\OpenWrench-0.3.0.dev2-setup.exe -Algorithm SHA256
Get-Content .\OpenWrench-0.3.0.dev2-setup.exe.sha256
```

The hashes should match. Run the installer as your normal Windows user.
It requires 64-bit Windows 10 1809 or later and includes Python, Qt and PDFium.
No separate Python installation is needed. The default program directory is
`%LOCALAPPDATA%\Programs\OpenWrench`; the Start Menu shortcut launches the app.
A desktop shortcut is optional. The workspace remains separately under
`%LOCALAPPDATA%\OpenWrench\OpenWrench`, as shown in Settings.

Before upgrading an existing workspace, use Settings to save a database backup.
Close OpenWrench, then install the new version over the existing installation.
Existing vehicles, manuals and diagnostic history remain in the workspace.
An old extracted portable bundle can remain separately; use the new Start Menu
shortcut so that you test the installed version.

## Acceptance on your computer

1. Launch from the Start Menu and confirm Settings shows `0.3.0.dev2` and schema 6.
2. Add/edit a test vehicle, log mileage/service, close and reopen the app.
3. Import a lawful PDF and an offline HTML folder/ZIP. Search, open pages,
   follow local links and check the import/resource reports.
4. Record a simulator session, review its graph/codes, and save/resume a guide.
   Simulator output is labelled and does not establish real hardware support.
5. Back up, change test data, and restore the backup. Also try an original
   schema-5 backup if available: sessions, samples, codes and manuals must survive,
   and a pre-restore safety backup must be created. Recording must be stopped.
6. Uninstall through Windows Installed apps and choose **No** if asked to remove
   the workspace. Reinstall and confirm your records are still present.

Silent uninstall preserves the workspace without prompting. Interactive data
removal is an explicit opt-in; it is not part of automated acceptance.
Keep personal manuals and database backups private.

## Build and automated acceptance

From a Windows Python 3.12 development environment with Inno Setup 6 available:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m build
python scripts/build_desktop.py
python scripts/make_installer.py --source-dir dist/OpenWrench --output-dir dist
```

CI uses the real Windows runner to build the current application and the original
`d6426b5` application. It packages both, installs the previous development
version into a path containing spaces, upgrades to the current version, checks
the per-user registry entry/Start Menu/icon/version, exercises native startup
and the installed PDF/HTML/restore workers, and silently uninstalls. Hashes of
the synthetic workspace, document cache and backup must survive install,
upgrade and uninstall. Acceptance refuses an account with existing OpenWrench
data or an installation, so run it only in an isolated Windows CI account.

The `validation-Windows` artifact retains pytest XML, installer/uninstaller logs
and `installer-acceptance/results.json`. The native installer is uploaded only
after acceptance succeeds. Ubuntu independently exercises the full suite,
source/native packaging and packaged PDF/HTML/schema-5 recovery.

The full public-release binary/source license audit, code signing, physical USB
compatibility and manual desktop acceptance remain separate from this
development installer.
