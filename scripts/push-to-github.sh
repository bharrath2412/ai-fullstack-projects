#!/usr/bin/env bash
# Create-and-push helper for GitHub, tuned for bharrath2412.
#
#   ./scripts/push-to-github.sh                        # ai-fullstack-projects (HTTPS)
#   ./scripts/push-to-github.sh my-other-name          # custom repo name
#   ./scripts/push-to-github.sh my-other-name --ssh    # git@github.com:...
#   ./scripts/push-to-github.sh --url /tmp/test.git    # any remote (GitLab, local, ...)
#
# It never needs a token stored anywhere: with HTTPS git asks for your username
# and a personal access token as the password; with SSH your key is used.
set -euo pipefail

OWNER="${GITHUB_OWNER:-bharrath2412}"
REPO_NAME="ai-fullstack-projects"
PROTOCOL="https"
REMOTE_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh) PROTOCOL="ssh" ;;
    --https) PROTOCOL="https" ;;
    --url) REMOTE_URL="${2:-}"; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) REPO_NAME="$1" ;;
  esac
  shift
done

cd "$(dirname "$0")/.."

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: uncommitted changes — commit them first (git add -A && git commit -m 'wip')" >&2
  exit 1
fi

if [[ -z "$REMOTE_URL" ]]; then
  if [[ "$PROTOCOL" == "ssh" ]]; then
    REMOTE_URL="git@github.com:$OWNER/$REPO_NAME.git"
  else
    REMOTE_URL="https://github.com/$OWNER/$REPO_NAME.git"
  fi
fi

if [[ -z "${REPO_NAME}" || "$REMOTE_URL" != *github.com* ]]; then
  # local/other remote: skip the GitHub-specific pre-flight
  exec ./scripts/push-to-repo.sh "$REMOTE_URL"
fi

NEW_REPO_URL="https://github.com/new?name=${REPO_NAME}&description=Four%20production-shaped%20projects%3A%20React%2BExpress%20web%20app%2C%20AI%20agent%2C%20ML%20service%2C%20RAG%20app&visibility=public"

echo "==> target: https://github.com/$OWNER/$REPO_NAME"

# Does the repo exist yet? ls-remote is authoritative; the API check is only a hint
# (unauthenticated API calls get rate-limited, which must not block the push).
if GIT_TERMINAL_PROMPT=0 timeout 20 git ls-remote "$REMOTE_URL" >/dev/null 2>&1; then
  echo "==> repository exists and is reachable"
else
  API_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://api.github.com/repos/$OWNER/$REPO_NAME" || echo "000")
  case "$API_CODE" in
    200) echo "==> repo exists in the API but git could not read it — check your credentials" ;;
    404) echo "==> '$REPO_NAME' does not exist yet on GitHub" ;;
    *)   echo "==> could not verify via API (HTTP $API_CODE) — assuming it is not reachable yet" ;;
  esac

  cat <<EOF

Create the empty repository first (do NOT add a README, .gitignore or license —
this repo already has all three, and an initialised remote causes a conflict):

    $NEW_REPO_URL

Then run this script again:

    ./scripts/push-to-github.sh $REPO_NAME

If you would rather keep it private, use "Private" in the GitHub form; nothing
else changes.

EOF
  exit 1
fi

exec ./scripts/push-to-repo.sh "$REMOTE_URL"
