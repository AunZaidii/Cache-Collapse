#!/usr/bin/env bash
# CacheCollapse one-shot deploy for a fresh Ubuntu cloud VM.
# Usage on the VM:   bash deploy.sh
set -e

echo "== CacheCollapse deploy =="

# 1) Install Docker if it isn't there.
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sudo sh
fi

# 2) Build and start all 9 containers in the background.
echo "Building and starting the stack (first run takes a few minutes)..."
sudo docker compose up --build -d

# 3) Show where it is.
IP=$(curl -fsS https://ifconfig.me 2>/dev/null || echo "<server-ip>")
echo
echo "== Done. CacheCollapse is running. =="
echo "  Dashboard : http://$IP:8090"
echo "  Shop      : http://$IP:8090/shop.html"
echo "  Grafana   : http://$IP:3000   (user: admin / pass: admin)"
echo "  Prometheus: http://$IP:9090"
echo
echo "Open ports 8090, 3000, 9090 in your cloud firewall to reach these."
echo "To stop:  sudo docker compose down"
