#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
#  WhisperX – GitHub push helper
#
#  Run this after generating a Personal Access Token with the correct
#  scope. See README.md → "Pushing to GitHub" for details.
# ──────────────────────────────────────────────────────────────────
set -e

# ── 1. Ask the user for a fresh PAT ──
read -r -p "Paste a fresh GitHub PAT with 'repo' scope (or fine-grained Contents:Write): " TOKEN
if [ -z "$TOKEN" ]; then
    echo "No token provided. Aborting."
    exit 1
fi

cd "$(dirname "$0")"

# ── 2. (Re)create the remote with the new token ──
git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/Yuki77394/Whisper.git"

# ── 3. Push ──
echo "Pushing to https://github.com/Yuki77394/Whisper ..."
git push -u origin main

# ── 4. Scrub the token from the local remote URL ──
git remote remove origin
git remote add origin https://github.com/Yuki77394/Whisper.git

echo ""
echo "✓ Push complete. Token scrubbed from local git config."
echo "View your repo at: https://github.com/Yuki77394/Whisper"
