#!/usr/bin/env bash
# Push this monorepo to your own GitHub/GitLab repository.
#
#   ./scripts/push-to-repo.sh git@github.com:you/your-repo.git
#   ./scripts/push-to-repo.sh https://github.com/you/your-repo.git main
#
# Modes
#   * remote is empty             -> pushes this single clean commit as `main`
#   * remote already has commits  -> merges the two histories (nothing is deleted)
#
# Merge conflicts are auto-resolved for the three predictable files, using the
# policy documented in PUSH-TO-YOUR-REPO.md. "yours" here always means the files
# already in the remote repository, because that repo keeps its identity:
#   README.md                     -> the remote's is kept, this project README -> PROJECTS.md
#   .gitignore                    -> union of both files
#   .github/workflows/ci.yml      -> the remote's is kept, this one -> ci-projects.yml
# Any other conflict stops the run so you can resolve it deliberately.
#
# Never force-pushes. Never deletes remote branches.
set -euo pipefail

REMOTE_URL="${1:-}"
BRANCH="${2:-main}"

if [[ -z "$REMOTE_URL" ]]; then
  echo "usage: $0 <git-remote-url> [branch]" >&2
  exit 1
fi

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: the working tree has uncommitted changes." >&2
  echo "       commit or stash them first:  git add -A && git commit -m \"wip\"" >&2
  exit 1
fi

git config user.name  >/dev/null 2>&1 || git config user.name  "Project Maintainer"
git config user.email >/dev/null 2>&1 || git config user.email "dev@example.com"

echo "==> repository: $ROOT"
echo "==> target:     $REMOTE_URL (branch: $BRANCH)"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git fetch --quiet origin || true

REMOTE_HAS_COMMITS=0
if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  REMOTE_HAS_COMMITS=$(git rev-list --count "origin/$BRANCH")
fi

if [[ "$REMOTE_HAS_COMMITS" == "0" ]]; then
  echo "==> remote is empty: pushing this history as '$BRANCH'"
  git branch -M "$BRANCH" 2>/dev/null || true
  git push -u origin "$BRANCH"
  echo
  echo "Done. Verify with: git log --oneline -3 && git remote -v"
  exit 0
fi

echo "==> remote already has $REMOTE_HAS_COMMITS commit(s) on '$BRANCH'"
git fetch origin "$BRANCH"
git branch -M "$BRANCH" 2>/dev/null || true

if git merge-base --is-ancestor "origin/$BRANCH" HEAD; then
  echo "    local history already contains the remote history — fast-forward push"
  git push -u origin "$BRANCH"
  exit 0
fi

echo "    merging unrelated histories"
if ! git merge --no-edit --allow-unrelated-histories "origin/$BRANCH"; then
  echo "    merge reported conflicts — applying the documented resolutions"
  mapfile -t CONFLICTS < <(git diff --name-only --diff-filter=U)

  for path in "${CONFLICTS[@]}"; do
    case "$path" in
      README.md)
        # Stage 2 = this repo ("ours"), stage 3 = the remote being merged in ("theirs").
        # The remote repository keeps its own README; this project's README is preserved
        # beside it as PROJECTS.md.
        if [[ ! -f PROJECTS.md ]] && git show ":2:README.md" > PROJECTS.md 2>/dev/null; then
          echo "      README.md        -> kept the remote's, this README saved as PROJECTS.md"
          git add PROJECTS.md
        else
          echo "      README.md        -> kept the remote's"
        fi
        git checkout --theirs -- README.md && git add README.md
        ;;
      .gitignore)
        {
          cat .gitignore
          echo
          echo "# ---- added with the four-project import"
          git show ":3:.gitignore" 2>/dev/null | sort -u
        } | awk '!seen[$0]++ || $0 == ""' > .gitignore.merged
        mv .gitignore.merged .gitignore
        git add .gitignore
        echo "      .gitignore       -> merged (union of both)"
        ;;
      .github/workflows/ci.yml)
        if [[ ! -f .github/workflows/ci-projects.yml ]] && git show ":2:.github/workflows/ci.yml" > .github/workflows/ci-projects.yml 2>/dev/null; then
          git add .github/workflows/ci-projects.yml
          echo "      ci.yml           -> kept the remote's, this one renamed to ci-projects.yml"
        fi
        git checkout --theirs -- .github/workflows/ci.yml && git add .github/workflows/ci.yml
        ;;
      *)
        echo "      $path -> needs your decision"
        echo
        echo "Automatic resolution is not safe here. Resolve the remaining files, then:"
        echo "  git add <files> && git commit --no-edit && git push -u origin $BRANCH"
        exit 1
        ;;
    esac
  done

  git commit --no-edit
fi

git push -u origin "$BRANCH"
echo
echo "Done. Both histories are preserved on '$BRANCH'."
echo "Verify with: git log --oneline --graph -6 && git remote -v"
