Yes. You can set both AuthorDate and CommitDate when creating a Git commit.

For example, if you're importing work that was actually completed on September 11, 2026:

1. Stage your changes
Shell
git add .
2. Commit with both historical dates
Shell
GIT_AUTHOR_DATE="2026-09-11T17:33:51+05:30" \
GIT_COMMITTER_DATE="2026-09-11T17:33:51+05:30" \
git commit -m "Add authentication"

This sets:

AuthorDate: September 11, 2026, 17:33:51 IST
CommitDate: September 11, 2026, 17:33:51 IST

Git supports specifying these dates independently.

3. Verify
Shell
git log -1 --format=fuller

You'll see both timestamps.

Important distinction

If you use:

Shell
git commit --date="2026-09-11T17:33:51+05:30" -m "Add authentication"

Only the AuthorDate is explicitly set. The CommitDate normally remains the current time.
