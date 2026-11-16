#!/usr/bin/env bash
# Push to GitHub using a token supplied at runtime via GITHUB_TOKEN.
#
#   GITHUB_TOKEN=github_pat_xxx ./scripts/push-with-token.sh
#   GITHUB_TOKEN=github_pat_xxx ./scripts/push-with-token.sh my-repo-name
#
# The token is never written to disk, never placed in the remote URL and never
# stored in .git/config: it is handed to git through a temporary GIT_ASKPASS
# helper that is deleted on exit (including on failure or Ctrl-C).
set -euo pipefail

OWNER="${GITHUB_OWNER:-bharrath2412}"
REPO_NAME="${1:-ai-fullstack-projects}"
BRANCH="${2:-main}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "error: GITHUB_TOKEN is not set." >&2
  echo "       GITHUB_TOKEN=<fine-grained PAT with Contents:write> $0 $REPO_NAME" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is dirty — commit first." >&2
  exit 1
fi

ASKPASS="$(mktemp)"
cleanup() { rm -f "$ASKPASS"; }
trap cleanup EXIT INT TERM

cat > "$ASKPASS" <<'HELPER'
#!/bin/sh
# git calls this with a prompt string; answer with token-based credentials.
case "$1" in
  *sername*) printf '%s\n' "x-access-token" ;;
  *)         printf '%s\n' "$GITHUB_TOKEN" ;;
esac
HELPER
chmod 700 "$ASKPASS"

URL="https://github.com/$OWNER/$REPO_NAME.git"
echo "==> target: $URL (branch: $BRANCH)"

# Read-only pre-flight: proves the token can see the repo before we push.
if ! GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 git ls-remote --heads "$URL" >/dev/null 2>&1; then
  echo "error: cannot read $URL with that token." >&2
  echo "       check: repo name, token expiry, and that the token has" >&2
  echo "       'Contents: Read and write' on this repository." >&2
  exit 1
fi

# Push via the URL itself (not through a stored remote) so nothing credential-related
# persists in .git/config. No force: if the remote somehow has commits we stop and say so.
if ! GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 \
     git push "$URL" "refs/heads/$BRANCH:refs/heads/$BRANCH"; then
  echo
  echo "error: push rejected. If the remote already has commits, use:" >&2
  echo "       ./scripts/push-to-repo.sh https://github.com/$OWNER/$REPO_NAME.git" >&2
  exit 1
fi

echo
echo "==> pushed. verify:"
echo "    https://github.com/$OWNER/$REPO_NAME"
