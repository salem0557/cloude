#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu droplet (DigitalOcean, etc.).
# Run as root:   bash setup.sh
# It installs Docker + git, clones the repo, and enables auto-deploy from GitHub.
set -euo pipefail

REPO_URL="https://github.com/salem0557/cloude.git"
TARGET="/opt/cloude"

echo "==> Installing git & Docker…"
apt-get update -y
apt-get install -y git curl
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Cloning the repo to $TARGET…"
if [ ! -d "$TARGET/.git" ]; then
  git clone "$REPO_URL" "$TARGET"
fi
cd "$TARGET"
git checkout main
git pull --ff-only origin main || true

echo "==> Preparing config…"
if [ ! -f bot/.env ]; then
  cp bot/config.example.env bot/.env
  echo
  echo "   ⚠️  Now edit your keys:   nano $TARGET/bot/.env"
  echo "       (set BOT_MODE, CONFIRM_LIVE, BINANCE_API_KEY/SECRET, …)"
fi

echo "==> Installing auto-deploy timer (pulls new versions every 3 min)…"
cp deploy/cryptobot-autodeploy.service /etc/systemd/system/
cp deploy/cryptobot-autodeploy.timer  /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cryptobot-autodeploy.timer

echo
echo "==> Done. Next steps:"
echo "   1) nano $TARGET/bot/.env        # put your keys"
echo "   2) cd $TARGET && docker compose -f bot/docker-compose.yml up -d --build"
echo "   3) Open the dashboard:  http://<your-droplet-ip>:8000"
echo "   Logs:  docker compose -f bot/docker-compose.yml logs -f"
