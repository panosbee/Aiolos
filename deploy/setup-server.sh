#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  XDART-Φ × XHEART — First-Time Server Setup Script
#
#  Tested on: Ubuntu 22.04/24.04 (Hetzner CX31 or similar)
#
#  Usage:
#    1. SSH into your server
#    2. Clone the repo
#    3. Run: chmod +x deploy/setup-server.sh && ./deploy/setup-server.sh
#
#  © Panos Skouras — Salimov MON IKE, 2026
# ══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Check root ──
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo ./deploy/setup-server.sh)"
fi

info "═══════════════════════════════════════════════"
info "  XDART-Φ × XHEART — Server Setup"
info "═══════════════════════════════════════════════"
echo

# ── 1. System updates ──
info "Step 1/7: System updates..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    ufw \
    fail2ban

# ── 2. Install Docker ──
info "Step 2/7: Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    info "Docker installed successfully"
else
    info "Docker already installed: $(docker --version)"
fi

# Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null; then
    apt-get install -y -qq docker-compose-plugin
fi
info "Docker Compose: $(docker compose version --short)"

# ── 3. Create xdart user ──
info "Step 3/7: Creating xdart user..."
if ! id "xdart" &>/dev/null; then
    useradd -m -s /bin/bash -G docker xdart
    info "User 'xdart' created and added to docker group"
else
    usermod -aG docker xdart
    info "User 'xdart' already exists, ensured docker group membership"
fi

# ── 4. Firewall ──
info "Step 4/7: Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
echo "y" | ufw enable
info "Firewall configured: SSH + HTTP + HTTPS only"

# ── 5. Fail2ban ──
info "Step 5/7: Configuring fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban
info "Fail2ban active"

# ── 6. Create app directory ──
info "Step 6/7: Setting up application directory..."
APP_DIR="/opt/xdart-phi"
mkdir -p "$APP_DIR"

# Check if we're running from the repo
if [[ -f "docker-compose.yml" ]]; then
    cp -r . "$APP_DIR/"
    info "Application files copied to $APP_DIR"
else
    warn "Run this script from the repo root, or clone manually to $APP_DIR"
fi

chown -R xdart:xdart "$APP_DIR"

# ── 7. Setup instructions ──
info "Step 7/7: Final setup..."
echo
info "═══════════════════════════════════════════════"
info "  Server setup complete!"
info "═══════════════════════════════════════════════"
echo
info "Next steps:"
echo "  1. cd $APP_DIR"
echo "  2. cp .env.production .env"
echo "  3. nano .env                    # Fill in API keys"
echo "  4. Edit deploy/nginx.conf       # Replace YOUR_DOMAIN with actual domain"
echo "  5. ./deploy/deploy.sh           # Build + start + SSL"
echo
info "Server specs check:"
echo "  RAM: $(free -h | awk '/^Mem/ {print $2}')"
echo "  CPU: $(nproc) cores"
echo "  Disk: $(df -h / | awk 'NR==2 {print $4}') free"
echo
