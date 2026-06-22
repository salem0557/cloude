"""Optional: publish the dashboard snapshot to GitHub so you can watch the bot
from anywhere (e.g. your phone) via the website.

To avoid triggering a GitHub Pages rebuild on every update (Pages has a low
build-rate limit), the snapshot is committed to a SEPARATE branch
(PUBLISH_BRANCH, default "bot-live") — NOT the Pages source branch. The
dashboard page reads it from that branch's raw URL when opened on the website.

Setup (in bot/.env):
  PUBLISH_DASHBOARD=true
  GITHUB_TOKEN=github_pat_...      # fine-grained PAT: Contents = Read & Write
  GH_REPO=salem0557/cloude
  PUBLISH_BRANCH=bot-live
  PUBLISH_SECONDS=60

Nothing here runs unless PUBLISH_DASHBOARD is true and a token is set, so the
bot works perfectly fine with publishing turned off.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL = HERE.parent / "docs" / "crypto" / "data" / "bot.json"
REPO_PATH = "docs/crypto/data/bot.json"
API = "https://api.github.com"


def _api(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cryptobot-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _get_sha(repo, branch, token):
    url = f"{API}/repos/{repo}/contents/{REPO_PATH}?ref={branch}"
    try:
        return _api("GET", url, token).get("sha")
    except Exception:
        return None  # file (or branch) doesn't exist yet


def publish(repo, branch, token):
    """Commit the current local bot.json to ``branch``. Returns True on success."""
    if not (repo and branch and token):
        return False
    try:
        content = LOCAL.read_bytes()
    except Exception:
        return False
    sha = _get_sha(repo, branch, token)
    body = {
        "message": "Update bot dashboard snapshot",
        "content": base64.b64encode(content).decode(),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    try:
        _api("PUT", f"{API}/repos/{repo}/contents/{REPO_PATH}", token, body)
        return True
    except Exception:
        return False
