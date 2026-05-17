# Recent Diff Discovery Skill

Use this skill to find recent product changes suitable for GuideSync documentation maintenance.

## Goal

Select recent changes that are likely to affect user-facing documentation and can be reproduced through the configured UI.

## Selection Criteria

Prefer changes that:

- are in frontend/UI repositories or clearly affect user-visible behaviour;
- touch labels, navigation, forms, onboarding, settings or user-visible workflow state;
- can be reproduced locally without production-only data or secrets;
- can be explained in a short guide;
- need 3-8 screenshots to document.

Avoid changes that:

- are purely backend/internal;
- require production credentials or customer data;
- require too many services for the first spike;
- need complex role modelling before any useful screenshot can be captured.

## Helper Scripts

From the CM3070 project root:

```bash
project/guidesync-mvp/scripts/recent_main_commits.sh
project/guidesync-mvp/scripts/recent_main_commits.sh "2 weeks ago"
project/guidesync-mvp/scripts/show_commit_files.sh /path/to/repo <commit>
```
