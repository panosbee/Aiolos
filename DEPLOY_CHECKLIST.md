# ══════════════════════════════════════════════════════════════
#  XDART-Φ × XHEART — DEPLOYMENT CHECKLIST
#  Βήμα-βήμα οδηγός για production deployment
#
#  Target: Hetzner VPS (CX31: 4 vCPU, 8GB RAM, 80GB SSD)
#  Estimated cost: ~€15/month
#
#  © Panos Skouras — Salimov MON IKE, 2026
# ══════════════════════════════════════════════════════════════

## ΒΗΜΑ 0: Προετοιμασία (local — πριν τον server)
- [x] Dockerfile — production-ready multi-stage build
- [x] docker-compose.yml — app + SearXNG + nginx + certbot
- [x] .env.production — template χωρίς secrets
- [x] .gitignore — excludes .env, perception.db, qdrant_storage, logs
- [x] .dockerignore — excludes heavy files from build context
- [x] deploy/nginx.conf — reverse proxy + SSL + rate limiting
- [x] deploy/setup-server.sh — first-time server setup (Docker, UFW, fail2ban)
- [x] deploy/deploy.sh — build + start + SSL + backup + status
- [x] deploy/init-data.sh — populate data volume with identity files
- [x] Security: hardcoded API keys αφαιρέθηκαν από config.py → .env only
- [x] Security: CORS_ORIGINS configurable (default "*" for dev, restricted in prod)
- [x] requirements.txt — uvicorn[standard] for production performance

## ΒΗΜΑ 1: Αγορά Domain + VPS

### Domain
- [ ] Πάρε domain (π.χ. Namecheap, Cloudflare Registrar)
- [ ] Πρόταση: aiolos.ai, xdart.ai, ή κάτι branding-ready
- [ ] Point DNS A record → VPS IP address (TTL: 300)

### VPS (Hetzner Cloud — recommended)
- [ ] Κάνε account στο https://console.hetzner.cloud
- [ ] Create server:
  - Location: Falkenstein (DE) ή Helsinki (FI) — closest to EU
  - Image: Ubuntu 24.04
  - Type: CX31 (4 vCPU, 8GB RAM, 80GB SSD) — €11.49/month
  - Networking: Enable IPv4
  - SSH Key: Add your SSH public key
- [ ] Note the IP address: _______________

## ΒΗΜΑ 2: Πρώτη σύνδεση στο server

```bash
# SSH into server
ssh root@<YOUR_IP>

# Update system + install Docker + firewall + fail2ban
# Option A: Clone repo and run setup script
git clone <YOUR_REPO_URL> /opt/xdart-phi
cd /opt/xdart-phi
chmod +x deploy/setup-server.sh deploy/deploy.sh deploy/init-data.sh
./deploy/setup-server.sh

# Option B: Manual (if no git repo yet — copy files via scp)
scp -r . root@<YOUR_IP>:/opt/xdart-phi/
ssh root@<YOUR_IP>
cd /opt/xdart-phi
chmod +x deploy/*.sh
./deploy/setup-server.sh
```

## ΒΗΜΑ 3: Ρύθμιση .env

```bash
cd /opt/xdart-phi
cp .env.production .env
nano .env
```

Συμπλήρωσε τα κλειδιά:
- [ ] OPENAI_API_KEY — DeepSeek: sk-c27...
- [ ] EMBEDDING_API_KEY — OpenAI: sk-proj-k6N...
- [ ] FRED_API_KEY — 94fe...
- [ ] FINNHUB_API_KEY — d7cv...
- [ ] BRAVE_SEARCH_API_KEY — BSAv...
- [ ] ELEVENLABS_API_KEY — sk_24...
- [ ] ELEVENLABS_VOICE_ID — KmYC...
- [ ] TELEGRAM_BOT_TOKEN — (αν θες proactive alerts)
- [ ] TELEGRAM_CHAT_ID — (αν θες proactive alerts)
- [ ] CORS_ORIGINS — https://yourdomain.com

## ΒΗΜΑ 4: Ρύθμιση domain στο nginx

```bash
# Αντικατέστησε YOUR_DOMAIN με το πραγματικό domain
sed -i 's/YOUR_DOMAIN/yourdomain.com/g' deploy/nginx.conf
```

## ΒΗΜΑ 5: Αρχικοποίηση data volume

```bash
# Αντιγράφει character_state.json, immediate_memory.json,
# self_awareness_brief.json, wisdom_calibration.json,
# qdrant_storage/ στο Docker volume
./deploy/init-data.sh
```

## ΒΗΜΑ 6: Deploy!

```bash
./deploy/deploy.sh
```

Αυτό κάνει:
1. ✓ Validates .env
2. ✓ Builds Docker image
3. ✓ Starts xdart + searxng + nginx
4. ✓ Waits for health check
5. ✓ Reports status

## ΒΗΜΑ 7: SSL Certificate

```bash
# Get Let's Encrypt certificate (free)
./deploy/deploy.sh --ssl-only

# Restart nginx to pick up certs
docker compose restart nginx
```

## ΒΗΜΑ 8: Verification

```bash
# Check all services
./deploy/deploy.sh --status

# Test health endpoint
curl https://yourdomain.com/xdart/health

# Test chat
curl -X POST https://yourdomain.com/xdart/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Γεια σου Αίολε"}'

# Watch logs
./deploy/deploy.sh --logs
```

## ΒΗΜΑ 9: Ongoing Operations

```bash
# Update code (after pushing changes)
cd /opt/xdart-phi && git pull
./deploy/deploy.sh --update

# Backup data
./deploy/deploy.sh --backup

# View logs
./deploy/deploy.sh --logs

# SSH tunnel for local access to API (optional)
ssh -L 8000:localhost:8000 root@<YOUR_IP>
```

## Κόστος/μήνα (εκτίμηση)
| Item | Κόστος |
|------|--------|
| Hetzner CX31 | €11.49 |
| Domain | ~€1/month (€12/year) |
| Let's Encrypt SSL | Free |
| DeepSeek API | ~€5-20 (ανάλογα χρήση) |
| OpenAI Embeddings | ~€0.50-2 |
| **Σύνολο** | **~€18-35/month** |

## Architecture on Server

```
┌─────────────────────────────────────────┐
│  Hetzner CX31 (Ubuntu 24.04)           │
│                                         │
│  ┌── nginx ──────────────────────────┐  │
│  │  :80 → :443 redirect              │  │
│  │  :443 → proxy to xdart:8000       │  │
│  │  SSL: Let's Encrypt (auto-renew)  │  │
│  │  Rate limiting: 10 req/s API      │  │
│  └────────────────────────────────────┘  │
│           │                              │
│  ┌── xdart-phi ──────────────────────┐  │
│  │  FastAPI + uvicorn                 │  │
│  │  Background: perception (3 loops)  │  │
│  │  Background: curiosity (30min)     │  │
│  │  Background: proactive (digest)    │  │
│  │  Background: consolidation (30min) │  │
│  │  Background: prophecy (6h)         │  │
│  │  Qdrant embedded (in-process)      │  │
│  │  SQLite WAL (perception.db)        │  │
│  └────────────────────────────────────┘  │
│           │                              │
│  ┌── searxng ────────────────────────┐  │
│  │  Meta search engine (internal)     │  │
│  │  No rate limits, self-hosted       │  │
│  └────────────────────────────────────┘  │
│                                         │
│  Volume: /var/lib/docker/volumes/       │
│    xdart-data/ → character_state.json   │
│                   perception.db          │
│                   qdrant_storage/         │
│                   journals, logs          │
└─────────────────────────────────────────┘
```

## Troubleshooting

### App δεν ξεκινάει
```bash
docker compose logs xdart | tail -50
# Συνήθεις αιτίες: λάθος API key, missing .env variable
```

### SSL αποτυγχάνει
```bash
# Βεβαιώσου ότι DNS points στο server IP
dig yourdomain.com +short
# Πρέπει να δείχνει το IP του server
```

### Out of memory
```bash
# Qdrant embedded + SQLite + Python = ~2-3GB RAM
# Αν χρειάζεσαι περισσότερο, αναβάθμισε σε CX41 (16GB)
free -h
docker stats --no-stream
```

### Perception DB μεγαλώνει
```bash
# Compact SQLite (μέσα στο container)
docker compose exec xdart python -c "
import sqlite3
conn = sqlite3.connect('/app/data/perception.db')
conn.execute('VACUUM')
conn.close()
print('Compacted')
"
```
