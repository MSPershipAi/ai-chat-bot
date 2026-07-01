# Deployment Plan — Equilibrium AI Chat (Pership Chatbot)

> Full Docker deployment on a single VPS.  
> Everything runs inside Docker. Only Nginx is reachable from the public internet.

---

## Architecture

```
Public Internet
      │
   Port 80  ──► HTTP (Phase 1) / HTTP→HTTPS redirect (Phase 2)
   Port 443 ──► HTTPS (Phase 2 only)
      │
  ┌───┴──────────────────────────────────────────────────┐
  │          Docker Bridge Network  (pership-chatbot-network)    │
  │                                                      │
  │  nginx ──/api/──► backend:8000 ──► ollama:11434     │
  │    └──────/──────► frontend:3000                     │
  └──────────────────────────────────────────────────────┘
```

| Container | Image | Host Port | Internal Port |
|-----------|-------|-----------|---------------|
| `pership-chatbot-nginx` | `nginx:alpine` | **80** (443 in Phase 2) | — |
| `pership-chatbot-frontend` | `./frontend` Dockerfile | ❌ none | 3000 |
| `pership-chatbot-backend` | `./backend` Dockerfile | ❌ none | 8000 |
| `pership-chatbot-ollama` | `ollama/ollama:latest` | ❌ none | 11434 |
| `pership-chatbot-ollama-init` | `ollama/ollama:latest` | ❌ none | — (one-shot) |

> **Key rule:** `expose:` (not `ports:`) is used for backend, frontend, and ollama.  
> This means they are reachable inside Docker but **never** bound to the host NIC.

---

## Prerequisites

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose v2
sudo apt install docker-compose-plugin -y

# Verify
docker --version
docker compose version
```

---

## Step 1 — Firewall (UFW)

Open **only** ports 22 (SSH), 80 (HTTP), and 443 (HTTPS).

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

> ⚠️ Do **NOT** open ports 8000, 3000, or 11434 — those stay private inside Docker.

---

## Step 2 — Clone the repository

```bash
cd /opt
git clone https://github.com/<your-org>/ai-chat-bot.git
cd ai-chat-bot
```

---

## Step 3 — Configure .env

```bash
cp .env.production.example .env
nano .env
```

### .env values explained

```env
# ─── Backend ─────────────────────────────────────────────────
ENVIRONMENT=production
GROQ_API_KEY=<your_groq_key>
JWT_SECRET=<generate: openssl rand -base64 32>
AUTH_SECRET=<generate: openssl rand -base64 32>
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# ─── Admin ───────────────────────────────────────────────────
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=<strong_password>

# ─── Frontend ────────────────────────────────────────────────
# /api is relative — browser calls http://<vps-ip>/api/...
# Nginx proxies /api/ → backend:8000 internally.
# Phase 2: no change needed; SSL is handled by Nginx only.
NEXT_PUBLIC_API_BASE=/api

# ─── Ollama ──────────────────────────────────────────────────
# Docker DNS name — backend reaches ollama on the private network.
OLLAMA_BASE_URL=http://ollama:11434
# Model to auto-pull on first deploy (see https://ollama.com/library)
OLLAMA_MODEL=llama3.2
```

---

## Phase 1 — HTTP only (no domain, no SSL)

Use this to get the app running on a bare VPS IP first.

### nginx.conf (Phase 1 — active block)

```nginx
server {
    listen 80;
    server_name _;   # matches any hostname / bare IP

    client_max_body_size 100M;

    location /health {
        proxy_pass http://backend/health;
        access_log off;
    }

    location /api/ {
        proxy_pass         http://backend/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
        proxy_send_timeout 300s;
        proxy_set_header   Connection '';
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass         http://frontend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade     $http_upgrade;
        proxy_set_header   Connection  'upgrade';
        proxy_set_header   Host        $host;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 120s;
    }
}
```

### docker-compose.yml (Phase 1 — nginx section)

```yaml
nginx:
  image: nginx:alpine
  ports:
    - "80:80"      # only port 80 in Phase 1
    # - "443:443"  # Phase 2 — uncomment after SSL
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
    # - ./ssl:/etc/nginx/ssl:ro              # Phase 2
    # - certbot-webroot:/var/www/certbot:ro  # Phase 2
```

### Start the stack

```bash
docker compose up -d --build

# Monitor startup (ollama-init pulls the model, then exits)
docker compose logs -f ollama-init
docker compose logs -f backend

# Verify everything is healthy
docker compose ps
```

### Test Phase 1

```bash
curl http://<vps-ip>/health           # → {"status":"ok"}
curl http://<vps-ip>/api/             # → FastAPI response
# Open in browser: http://<vps-ip>

# Confirm internal ports are NOT reachable from outside:
curl http://<vps-ip>:8000             # Connection refused ✅
curl http://<vps-ip>:11434            # Connection refused ✅
curl http://<vps-ip>:3000             # Connection refused ✅
```

---

## Phase 2 — Add Domain + SSL (HTTPS)

Do this after Phase 1 is working and you have a domain pointed to the VPS.

### 2a. Point DNS to VPS

In your domain registrar / DNS provider, create an **A record**:

```
yourdomain.com      →  <vps-public-ip>
www.yourdomain.com  →  <vps-public-ip>
```

Wait for DNS propagation (up to 24h, usually minutes).

### 2b. Get SSL certificate (Let's Encrypt)

```bash
# Install certbot on the VPS host (outside Docker)
sudo apt install certbot -y

# Stop nginx temporarily so certbot can use port 80
docker compose stop nginx

# Issue certificate
sudo certbot certonly --standalone \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --agree-tos \
  -m your@email.com

# Copy certs into the ssl/ folder that docker-compose mounts
mkdir -p ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem  ssl/
sudo chmod 644 ssl/fullchain.pem ssl/privkey.pem
```

### 2c. Update nginx.conf

**Delete** the Phase 1 server block and **uncomment** the Phase 2 blocks.  
Replace `yourdomain.com` with your real domain.

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options    "nosniff" always;
    add_header X-Frame-Options           "SAMEORIGIN" always;
    add_header X-XSS-Protection          "1; mode=block" always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin" always;

    client_max_body_size 100M;

    location /health {
        proxy_pass http://backend/health;
        access_log off;
    }

    location /api/ {
        proxy_pass         http://backend/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
        proxy_send_timeout 300s;
        proxy_set_header   Connection '';
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass         http://frontend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade     $http_upgrade;
        proxy_set_header   Connection  'upgrade';
        proxy_set_header   Host        $host;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 120s;
    }
}
```

### 2d. Update docker-compose.yml

Uncomment the Phase 2 lines in the nginx service:

```yaml
nginx:
  ports:
    - "80:80"
    - "443:443"   # ← uncomment
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
    - ./ssl:/etc/nginx/ssl:ro                   # ← uncomment
    - certbot-webroot:/var/www/certbot:ro       # ← uncomment
```

Also uncomment in the `volumes:` section at the bottom:

```yaml
volumes:
  ollama-data:
  faiss-data:
  uploaded-docs:
  certbot-webroot:   # ← uncomment
```

### 2e. Restart nginx

```env
# .env — NEXT_PUBLIC_API_BASE stays /api (no change needed)
NEXT_PUBLIC_API_BASE=/api
```

```bash
docker compose up -d nginx
```

### Test Phase 2

```bash
curl -I https://yourdomain.com           # → 200 OK with SSL
curl https://yourdomain.com/api/health   # → {"status":"ok"}
curl http://yourdomain.com               # → 301 redirect to https://
```

### 2f. Auto-renew SSL (cron)

```bash
sudo crontab -e
# Add this line (runs twice daily, reloads nginx after renewal):
0 3,15 * * * certbot renew --quiet \
  && cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem /opt/ai-chat-bot/ssl/ \
  && cp /etc/letsencrypt/live/yourdomain.com/privkey.pem  /opt/ai-chat-bot/ssl/ \
  && docker exec pership-chatbot-nginx nginx -s reload
```

---

## Ollama Model Management

```bash
# List available models
docker exec pership-chatbot-ollama ollama list

# Pull a new model manually
docker exec pership-chatbot-ollama ollama pull mistral
docker exec pership-chatbot-ollama ollama pull phi3
docker exec pership-chatbot-ollama ollama pull gemma2

# Remove a model
docker exec pership-chatbot-ollama ollama rm llama3.2

# Models are stored in the ollama-data Docker volume (persists restarts)
```

---

## Useful Commands

```bash
# View all container statuses
docker compose ps

# Live logs
docker compose logs -f
docker compose logs -f backend
docker compose logs -f ollama
docker compose logs -f nginx

# Restart a single service
docker compose restart backend
docker compose restart nginx

# Rebuild after code changes
docker compose up -d --build backend
docker compose up -d --build frontend

# Stop everything
docker compose down

# Stop + remove volumes (⚠️ deletes ollama models & uploaded files)
docker compose down -v

# Shell into a container for debugging
docker exec -it pership-chatbot-backend bash
docker exec -it pership-chatbot-ollama bash
docker exec -it pership-chatbot-nginx sh
```

---

## Network Flow Summary

| Request from browser | Nginx action | Destination |
|----------------------|-------------|-------------|
| `http://<ip>/` | Serve directly | → `frontend:3000` |
| `http://<ip>/api/chat` | Strip `/api`, forward | → `backend:8000/chat` |
| `http://<ip>/health` | Forward | → `backend:8000/health` |
| `https://domain.com/` (Phase 2) | Serve via SSL | → `frontend:3000` |
| `http://domain.com/` (Phase 2) | 301 redirect | → `https://domain.com/` |
| `backend → ollama` | Docker DNS | → `ollama:11434` (private) |
| Port 8000 from internet | **BLOCKED** by UFW | ❌ |
| Port 3000 from internet | **BLOCKED** by UFW | ❌ |
| Port 11434 from internet | **BLOCKED** by UFW | ❌ |

---

## Troubleshooting

### Backend can't reach Ollama

```bash
# From inside the backend container:
docker exec pership-chatbot-backend curl http://ollama:11434/api/tags
# Should return JSON list of models
```

### Frontend 404 on /api/ routes

- Ensure `NEXT_PUBLIC_API_BASE=/api` in `.env`
- **Rebuild** frontend after any `.env` change (it's baked in at build time):
  ```bash
  docker compose up -d --build frontend
  ```

### Ollama model not found

```bash
# Check what models exist
docker exec pership-chatbot-ollama ollama list

# Re-run the init to pull the model
docker compose run --rm ollama-init
```

### Nginx SSL errors (Phase 2)

```bash
# Check certs exist and are readable
ls -la ssl/

# Check nginx logs
docker compose logs nginx

# Validate nginx config
docker exec pership-chatbot-nginx nginx -t
```

### Container won't start (healthcheck failing)

```bash
# Inspect the container
docker inspect pership-chatbot-backend | grep -A 20 Health

# Check logs for startup errors
docker compose logs backend --tail=50
```
