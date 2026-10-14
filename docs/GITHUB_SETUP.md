# Repository workflow

The repository exists at https://github.com/Spacecowboy-28/openwrench-desktop .
Milestone 1 merged through PR #1. Historical bundle-import instructions are
superseded by the existing Git history. Do not recreate or reinitialize it.

Milestone 2 starts from main commit 76c15985a16330b156095a490c8c84da097d8a53
on `dev/milestone-2`. Review its pull request and CI before a manual merge.

To test the development branch on your computer with an existing clone:

```sh
git fetch origin
git switch dev/milestone-2
git pull --ff-only origin dev/milestone-2
```

Preserve uncommitted local changes before switching branches. Follow README.md
for the virtual environment, tests and application launch. Never force-push main.
