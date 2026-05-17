# Repo Scope Skill

Use this skill when the GuideSync MVP needs repository context.

## Scope

Only inspect repositories listed in the incoming task JSON or explicitly provided by the user.

## Rules

- Treat configured repositories as source targets, not as the MVP implementation workspace.
- Do not switch branches, reset, clean, stash, rebase or modify source repositories unless explicitly requested.
- Prefer analysing the configured ref and specific commits without changing the working tree.
- Check `git status --short --branch` before any operation that could affect a working copy.
- If fresh remote refs are needed, use `git fetch origin`, not `git pull`, unless the owner explicitly asks to update the working tree.

## Helper Scripts

From the CM3070 project root:

```bash
project/guidesync-mvp/scripts/repo_status.sh
project/guidesync-mvp/scripts/fetch_scoped_repos.sh
```
