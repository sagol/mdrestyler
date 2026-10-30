#!/usr/bin/env bash
set -euo pipefail

# Publish the committed public site files to the gh-pages branch of sagol/mdrestyler.
# Requires Python 3.10+, git, tar and a git author identity.
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [ ! -f site/index.html ]; then
  echo 'error: site/index.html not found' >&2
  exit 1
fi
if [ -n "$(git status --porcelain -- site)" ]; then
  echo 'error: commit all site/ changes before deploying' >&2
  exit 1
fi

# get-url expands URL rewrites. Check every push destination, not the fetch URL.
PUSH_URL="$(git remote get-url --push --all origin)"
case "$PUSH_URL" in
  *$'\n'*) echo 'error: origin must have exactly one push destination' >&2; exit 1 ;;
esac
case "$PUSH_URL" in
  https://*@*) echo 'error: the push URL holds credentials; keep them out of the URL (a credential helper or git environment works with a plain https URL), or use SSH' >&2; exit 1 ;;
esac
case "$PUSH_URL" in
  https://github.com/sagol/mdrestyler|https://github.com/sagol/mdrestyler.git|https://github.com/sagol/mdrestyler/|\
  git@github.com:sagol/mdrestyler|git@github.com:sagol/mdrestyler.git|\
  ssh://git@github.com/sagol/mdrestyler|ssh://git@github.com/sagol/mdrestyler.git|\
  ssh://git@github.com:22/sagol/mdrestyler|ssh://git@github.com:22/sagol/mdrestyler.git) ;;
  *) echo 'error: the push destination must be the GitHub repository sagol/mdrestyler' >&2; exit 1 ;;
esac

SOURCE_SHA="$(git rev-parse HEAD)"
DEPLOY_GIT_DIR="$(git rev-parse --absolute-git-dir)"
DEPLOY_TMP="$(mktemp -d)"
trap 'rm -rf "$DEPLOY_TMP"' EXIT

# Stage from the committed snapshot with the same file list the workflow uses.
git archive "$SOURCE_SHA" site | tar -x -C "$DEPLOY_TMP"
python3 "$DEPLOY_TMP/site/stage.py" "$DEPLOY_TMP/public"

# A failed remote query aborts. Empty output means the branch does not exist yet.
REMOTE_HEAD="$(git ls-remote --heads "$PUSH_URL" refs/heads/gh-pages)"
REMOTE_SHA="$(printf '%s\n' "$REMOTE_HEAD" | awk '$2 == "refs/heads/gh-pages" {print $1}')"

# Build the commit in a temporary index; no branch is created and the working tree is untouched.
export GIT_INDEX_FILE="$DEPLOY_TMP/index"
git --git-dir="$DEPLOY_GIT_DIR" read-tree --empty
git -C "$DEPLOY_TMP/public" --git-dir="$DEPLOY_GIT_DIR" --work-tree="$DEPLOY_TMP/public" add --force --all -- .
TREE_SHA="$(git --git-dir="$DEPLOY_GIT_DIR" write-tree)"
COMMIT_SHA="$(git --git-dir="$DEPLOY_GIT_DIR" commit-tree "$TREE_SHA" -m "Publish site from $SOURCE_SHA")"

# An empty expected value also protects the first publication against a concurrent one.
echo "Publishing site files from $SOURCE_SHA to gh-pages..."
git push "--force-with-lease=refs/heads/gh-pages:${REMOTE_SHA}" "$PUSH_URL" "${COMMIT_SHA}:refs/heads/gh-pages"
echo "Done. Set GitHub Pages to deploy from the gh-pages branch, / (root)."
