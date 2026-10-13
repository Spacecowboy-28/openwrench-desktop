# GitHub setup and handoff

The connected GitHub account was reachable, but repository listing returned no
accessible repositories. The exposed connector has no repository-create action.
No remote was created, no files were pushed, and no PR or release was published.

Create a public repository named `openwrench-desktop` through GitHub's New
Repository page: https://github.com/new . Leave README, license and gitignore
initialization unchecked if you will push the prepared Git history below.
Give the connected GitHub app access to the repository, then provide its URL
in the next Work session. Do not grant access to unrelated repositories.

The handoff archive contains `openwrench-history.bundle` plus the readable source.
To preserve the prepared commit history with local Git:

```sh
git clone -b dev/milestone-1 openwrench-history.bundle openwrench-desktop
cd openwrench-desktop
git remote remove origin
git remote add origin https://github.com/YOUR_USERNAME/openwrench-desktop.git
git push origin main
git push -u origin dev/milestone-1
```

Authenticate through your normal Git credential manager. Do not paste access
tokens into chat, source files, or shell commands. Open a PR from
`dev/milestone-1` to `main`. CI runs tests and builds on Windows and Linux.
The source branch contains the development work, while main contains the initial
license/README baseline. Review successful CI before merging.

If the next session uses only GitHub file tools, initialize the new repository
with a README instead. The assistant must inspect its initial commit, preserve
it, and upload the prepared files to a new development branch. Do not force-push
over this initial history. A Git bundle is unnecessary for this alternative.

Suggested PR title: `Add native desktop foundation and local persistence`

Suggested PR body:

OpenWrench needs a desktop foundation before vehicle records and diagnostic
drivers. This adds a Python/Qt shell, SQLite settings and migrations, verified
database backups, dark/light themes, logging, failure handling, and Windows/Linux
build checks. Research and license decisions document the native-stack choice.
Vehicle editing and scans are intentionally outside this milestone. See
DEVELOPMENT_STATUS.md for local test evidence and platform limitations.
