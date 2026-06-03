#!/usr/bin/env bash
# Commit data/jobs.db back to the repo if it changed.
# [skip ci] keeps these commits from triggering the CI workflow.
set -euo pipefail

MESSAGE="${1:-chore(data): update db}"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git add -f data/jobs.db

if git diff --cached --quiet; then
  echo "No database changes to commit."
  exit 0
fi

git commit -m "${MESSAGE} [skip ci]"

# Rebase onto any commit another (serialized) run may have pushed, then push.
git pull --rebase --autostash origin "${GITHUB_REF_NAME}" || true
git push origin "HEAD:${GITHUB_REF_NAME}"
