#!/usr/bin/env bash
# Optional helper: create the GitHub repo and configure secrets.
# Requires `gh` CLI authenticated with a Personal Access Token.
#
# Usage:  bash scripts/configure_repo.sh
#         bash scripts/configure_repo.sh --dry-run    # only print what would be set

set -euo pipefail
DRY_RUN="${2:-}"

if ! command -v gh &>/dev/null; then
  echo "gh CLI not found. Create the repo manually at github.com/new"
  echo "Then add secrets via Settings > Secrets and variables > Actions."
  exit 1
fi

REPO="${1:-property-unfiltered}"
echo "Creating public repo: $REPO ..."
gh repo create "$REPO" --public --push --source=. --remote=origin

echo "Adding secrets (paste values when prompted)..."
echo "---"

add_secret() {
  local name=$1 desc=$2 optional=$3
  if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "  Would set: $name"
    return
  fi
  if [ -n "$optional" ]; then
    read -rp "  $name ($desc, optional — press Enter to skip): " val
    [ -z "$val" ] && { echo "  skipping $name"; return; }
  else
    read -rsp "  $name ($desc): " val; echo
    [ -z "$val" ] && { echo "  ERROR: $name is required"; exit 1; }
  fi
  echo "$val" | gh secret set "$name" --repo "$REPO"
}

add_secret "GOOGLE_API_KEY"    "Gemini API key"  ""
add_secret "GROQ_API_KEY"      "Groq API key"    "optional"
add_secret "PEXELS_API_KEY"    "Pexels API key"  "optional"
add_secret "YOUTUBE_CLIENT_SECRETS" "OAuth client secrets JSON" ""
add_secret "YOUTUBE_REFRESH_TOKEN" "OAuth refresh token" ""

echo "Secrets set. Workflows ready to run."