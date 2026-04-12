#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  XDART-Φ × XHEART — Deploy / Update Script
#
#  Usage:
#    ./deploy/deploy.sh              # Full deploy (build + start + SSL)
#    ./deploy/deploy.sh --update     # Rebuild and restart app only
#    ./deploy/deploy.sh --ssl-only   # Get/renew SSL certificate only
#    ./deploy/deploy.sh --logs       # Tail logs
#    ./deploy/deploy.sh --status     # Check status
#    ./deploy/deploy.sh --backup     # Backup data
#
#  © Panos Skouras — Salimov MON IKE, 2026
# ══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}═══ $1 ═══${NC}"; }

# ── Find project root ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Validate environment ──
check_env() {
    if [[ ! -f ".env" ]]; then
        error ".env file not found. Copy .env.production to .env and fill in your keys."
    fi
    # Check critical keys are set
    source .env
    if [[ -z "${OPENAI_API_KEY:-}" || "$OPENAI_API_KEY" == *"your-"* ]]; then
        error "OPENAI_API_KEY not set in .env"
    fi
    if [[ -z "${EMBEDDING_API_KEY:-}" || "$EMBEDDING_API_KEY" == *"your-"* ]]; then
        error "EMBEDDING_API_KEY not set in .env"
    fi
    info "Environment validated"
}

# ── Extract domain from nginx config ──
get_domain() {
    grep -m1 "server_name" deploy/nginx.conf | awk '{print $2}' | tr -d ';'
}

# ── SSL Certificate ──
setup_ssl() {
    local domain
    domain=$(get_domain)
    if [[ "$domain" == "YOUR_DOMAIN" ]]; then
        error "Replace YOUR_DOMAIN in deploy/nginx.conf with your actual domain first!"
    fi

    step "Setting up SSL for $domain"

    # Create certbot directories
    mkdir -p deploy/certbot/conf deploy/certbot/www

    # First, start nginx with HTTP only (for ACME challenge)
    # Create a temporary HTTP-only nginx config
    cat > /tmp/nginx-http-only.conf << 'TMPEOF'
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 200 'XDART-Phi SSL setup in progress';
        add_header Content-Type text/plain;
    }
}
TMPEOF

    # Start temporary nginx for ACME challenge
    docker run -d --name certbot-nginx --rm \
        -p 80:80 \
        -v "$PWD/deploy/certbot/www:/var/www/certbot" \
        -v /tmp/nginx-http-only.conf:/etc/nginx/conf.d/default.conf:ro \
        nginx:alpine 2>/dev/null || true

    # Get certificate
    docker run --rm \
        -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
        -v "$PWD/deploy/certbot/www:/var/www/certbot" \
        certbot/certbot certonly \
        --webroot --webroot-path=/var/www/certbot \
        --email "admin@$domain" \
        --agree-tos --no-eff-email \
        -d "$domain"

    # Stop temporary nginx
    docker stop certbot-nginx 2>/dev/null || true

    info "SSL certificate obtained for $domain"
}

# ── Build & Start ──
deploy_full() {
    check_env

    step "Building XDART-Φ Docker image"
    docker compose build --no-cache
    info "Image built"

    step "Starting services"
    docker compose up -d
    info "Services started"

    step "Waiting for health check..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if curl -sf http://localhost:8000/xdart/health > /dev/null 2>&1; then
            info "XDART-Φ is healthy!"
            break
        fi
        retries=$((retries - 1))
        sleep 2
    done

    if [[ $retries -eq 0 ]]; then
        warn "Health check timed out — check logs: docker compose logs xdart"
    fi

    step "Deployment complete"
    docker compose ps
    echo
    local domain
    domain=$(get_domain)
    info "Dashboard: https://$domain/"
    info "API: https://$domain/xdart/"
    info "Health: https://$domain/xdart/health"
}

# ── Update (rebuild app, keep data) ──
update_app() {
    check_env
    step "Updating XDART-Φ"
    docker compose build xdart
    docker compose up -d xdart
    info "Updated and restarted"
    docker compose ps
}

# ── Backup ──
backup_data() {
    step "Backing up XDART-Φ data"
    local backup_dir="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"

    # Copy data from Docker volume
    docker compose exec xdart tar czf - /app/data 2>/dev/null > "$backup_dir/xdart-data.tar.gz" || {
        warn "Container not running — trying volume directly"
        docker run --rm -v xdart-phi_xdart-data:/data alpine tar czf - /data > "$backup_dir/xdart-data.tar.gz"
    }

    info "Backup saved to $backup_dir/xdart-data.tar.gz"
    ls -lh "$backup_dir/"
}

# ── Status ──
show_status() {
    step "XDART-Φ Status"
    docker compose ps
    echo
    if curl -sf http://localhost:8000/xdart/health 2>/dev/null | python3 -m json.tool 2>/dev/null; then
        info "API is responding"
    else
        warn "API not responding"
    fi
    echo
    echo "Disk usage:"
    docker system df 2>/dev/null || true
}

# ── Main ──
case "${1:-}" in
    --update)    update_app ;;
    --ssl-only)  setup_ssl ;;
    --logs)      docker compose logs -f --tail=100 ;;
    --status)    show_status ;;
    --backup)    backup_data ;;
    --help|-h)
        echo "Usage: $0 [--update|--ssl-only|--logs|--status|--backup|--help]"
        echo "  (no args)   Full deploy: build + start + SSL"
        echo "  --update    Rebuild and restart app only"
        echo "  --ssl-only  Get/renew SSL certificate"
        echo "  --logs      Tail application logs"
        echo "  --status    Check service status"
        echo "  --backup    Backup data volume"
        ;;
    *)           deploy_full ;;
esac
