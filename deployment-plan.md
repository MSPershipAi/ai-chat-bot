# Equilibrium AI Chat - Deployment Plan

**Target Deployment**: Docker + Docker Compose on budget VPS (~$10/month)  
**Timeline**: No immediate deadline  
**Expected Scale**: < 100 users  
**Status**: Planning Phase

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Phase 0: Ollama + Gemma Model Setup on VPS](#phase-0-ollama--gemma-model-setup-on-vps) ⭐ **NEW**
4. [Phase 1: Containerization](#phase-1-containerization)
5. [Phase 2: CI/CD Pipeline](#phase-2-cicd-pipeline)
6. [Phase 3: Deployment](#phase-3-deployment)
7. [Phase 4: Post-Deployment](#phase-4-post-deployment)
8. [Cost Breakdown](#cost-breakdown)
9. [Troubleshooting](#troubleshooting)

---

## 🏗️ Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                   Linux VPS (Host)                       │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │          Docker Compose Network                  │    │
│  │                                                  │    │
│  │  ┌─────────────┐    ┌──────────────────────┐   │    │
│  │  │  Frontend   │    │      Backend         │   │    │
│  │  │  (Next.js)  │◄──►│     (FastAPI)        │   │    │
│  │  │  :3000      │    │     :8000            │   │    │
│  │  └─────────────┘    └──────────┬───────────┘   │    │
│  │         ▲                      │               │    │
│  │         │     ┌────────────────┘               │    │
│  │  ┌──────┴──┐  │  host.docker.internal:11434    │    │
│  │  │  Nginx  │  │                                │    │
│  │  │  :80    │  │                                │    │
│  │  │  :443   │  │                                │    │
│  │  └─────────┘  │                                │    │
│  └───────────────┼────────────────────────────────┘    │
│                  │  (bridge via extra_hosts)            │
│                  ▼                                      │
│  ┌───────────────────────────────────────────────┐     │
│  │  Ollama (Host Process — NOT in Docker)        │     │
│  │  Port: 11434                                  │     │
│  │  Model: embeddinggemma (Gemma 2B embeddings)  │     │
│  └───────────────────────────────────────────────┘     │
│                  │                                      │
│  ┌───────────────▼───────────────────────────────┐     │
│  │  Neon PostgreSQL  (External / Cloud DB)        │     │
│  │  (DATABASE_URL in .env)                        │     │
│  └────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
        ↓ Volumes
   FAISS Index + Uploaded Docs (Docker bind mounts)
```

**Key Components**:

- **Frontend**: Next.js in production-optimized container
- **Backend**: FastAPI + Python 3.12 with all dependencies
- **Reverse Proxy**: Nginx for routing and static file serving
- **Ollama** ⭐: Runs **directly on the VPS host** (not inside Docker) — serves the `embeddinggemma` Gemma model on port `11434`. The backend container reaches it via `host.docker.internal`.
- **Database**: Neon PostgreSQL (external cloud DB via `DATABASE_URL`)
- **Persistence**: Docker bind mounts for FAISS index and uploaded docs

---

## ✅ Pre-Deployment Checklist

### Backend Requirements

- [ ] Python 3.12 environment verified (not 3.14)
- [ ] All dependencies in `requirements.txt` tested
- [ ] `.env` file template created
- [ ] Database/FAISS index initialization scripts prepared
- [ ] API endpoints tested locally
- [ ] CORS settings verified for frontend domain

### Frontend Requirements

- [ ] Next.js build succeeds (`npm run build`)
- [ ] Environment variables configured (.env.local)
- [ ] API endpoint correctly points to backend URL
- [ ] All components compile without errors
- [ ] Performance optimized (images, code splitting)

### Infrastructure Requirements

- [ ] VPS provisioned (minimum **2GB RAM** for Ollama + all services)
- [ ] SSH access verified
- [ ] Docker & Docker Compose installed
- [ ] **Ollama installed on VPS host and `embeddinggemma` model pulled** ⭐
- [ ] Domain name registered (optional but recommended)
- [ ] SSL certificate ready or Let's Encrypt configured

### Secrets & Configuration

- [ ] All API keys documented (Groq API key, etc.)
- [ ] Database credentials prepared (Neon PostgreSQL URL)
- [ ] `AUTH_SECRET` / JWT secret key generated
- [ ] `OLLAMA_BASE_URL` set correctly in `.env`
- [ ] CORS allowed origins listed
- [ ] Admin credentials created

---

## 🤖 Phase 0: Ollama + Gemma Model Setup on VPS

> **Why Phase 0?** Your backend uses Ollama (`embeddinggemma`) for RAG document embeddings via `langchain-ollama`. Ollama runs **on the VPS host** (not inside Docker), and the backend container connects to it through `host.docker.internal:11434`. This must be done **before** starting Docker Compose.

### Step 0.1: VPS Hardware Requirements

| Resource | Minimum          | Recommended      |
| -------- | ---------------- | ---------------- |
| RAM      | 2 GB             | 4 GB             |
| CPU      | 1 vCPU           | 2 vCPU           |
| Disk     | 25 GB SSD        | 40 GB SSD        |
| OS       | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

> ⚠️ **Critical**: Ollama + embeddinggemma requires ~1-1.5 GB RAM. Running on a 1GB VPS **will cause OOM crashes**. Use minimum 2GB, preferably 4GB.

---

### Step 0.2: Install Ollama on VPS Host

```bash
# SSH into your VPS
ssh root@your_vps_ip

# Install Ollama (official one-liner)
curl -fsSL https://ollama.com/install.sh | sh

# Verify installation
ollama --version
```

---

### Step 0.3: Configure Ollama to Listen on All Interfaces

By default Ollama only listens on `127.0.0.1:11434`. Docker containers **cannot** reach this. You must configure Ollama to bind to `0.0.0.0`:

```bash
# Create a systemd override for Ollama
sudo systemctl edit ollama
```

This opens a text editor. Add the following content:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Save and exit, then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl enable ollama   # Start on boot

# Verify Ollama is listening on all interfaces
ss -tlnp | grep 11434
# Should show: 0.0.0.0:11434 (not just 127.0.0.1:11434)

# Test the API
curl http://localhost:11434/api/tags
```

---

### Step 0.4: Create the `embeddinggemma` Model

Your app uses a **custom Ollama model** called `embeddinggemma`. This is likely a Gemma-based embedding model configured via a `Modelfile`. Create it on the VPS:

**Option A — If you have a Modelfile in your repo:**

```bash
# Navigate to project directory (after cloning)
cd /opt/equilibrium

# Create the model from your Modelfile
ollama create embeddinggemma -f ./Modelfile.embeddinggemma

# Verify model is created
ollama list
```

**Option B — Create a Modelfile from scratch (Gemma 2B embedding):**

```bash
# Create Modelfile for embeddinggemma
cat > /opt/equilibrium/Modelfile.embeddinggemma << 'EOF'
FROM gemma2:2b
# Custom embedding model based on Gemma 2B
PARAMETER temperature 0
PARAMETER num_ctx 4096
EOF

# Pull the base Gemma model first
ollama pull gemma2:2b

# Create embeddinggemma from Modelfile
ollama create embeddinggemma -f /opt/equilibrium/Modelfile.embeddinggemma

# List models to confirm
ollama list
```

> 💡 **Note**: If your local Modelfile uses a different base model (e.g., `nomic-embed-text`, `mxbai-embed-large`), adjust the `FROM` line accordingly. Check your local repo's `Modelfile` to confirm the exact base.

---

### Step 0.5: Test Embedding Works

```bash
# Test that embeddinggemma produces embeddings
curl http://localhost:11434/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "embeddinggemma", "prompt": "Hello, this is a test."}'

# Expected: a JSON response with an "embedding" array of floats
# {"embedding": [0.123, -0.456, ...]}
```

---

### Step 0.6: Verify Docker Can Reach Ollama

The backend container connects to Ollama via `host.docker.internal:11434`. This works because `docker-compose.yml` already has:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Verify this works after Docker is running (Step 3.2):

```bash
# Test from inside the backend container
docker-compose exec backend curl http://host.docker.internal:11434/api/tags

# Should return JSON list of models including embeddinggemma
```

---

### Step 0.7: Firewall — Keep Ollama Port Private

> ⚠️ **Security**: Do NOT expose port 11434 publicly. Ollama has no authentication. Keep it firewalled.

```bash
# Allow SSH, HTTP, HTTPS (already done in Step 3.4)
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# DO NOT add: ufw allow 11434/tcp  ← Keep Ollama private!

# Verify Ollama port is NOT publicly exposed
ufw status
# 11434 should NOT appear in the allowed list
```

Docker containers can still reach Ollama via `host.docker.internal` because that traffic stays on the loopback/bridge interface — it never goes through the external firewall.

---

### Step 0.8: Ollama Startup Check Script

Add this to `/opt/equilibrium/scripts/check-ollama.sh`:

```bash
#!/bin/bash
echo "🔍 Checking Ollama status..."

# Check if Ollama service is running
if systemctl is-active --quiet ollama; then
    echo "  ✅ Ollama service is running"
else
    echo "  ❌ Ollama is NOT running — starting..."
    sudo systemctl start ollama
fi

# Check if embeddinggemma model is available
if curl -s http://localhost:11434/api/tags | grep -q "embeddinggemma"; then
    echo "  ✅ embeddinggemma model is available"
else
    echo "  ❌ embeddinggemma model NOT found — recreating..."
    ollama create embeddinggemma -f /opt/equilibrium/Modelfile.embeddinggemma
fi

echo "✅ Ollama check complete!"
```

```bash
chmod +x /opt/equilibrium/scripts/check-ollama.sh

# Run before every docker-compose up
/opt/equilibrium/scripts/check-ollama.sh
```

---

### Phase 0 Summary Checklist

- [ ] VPS has 2GB+ RAM (4GB recommended)
- [ ] Ollama installed via official script
- [ ] Ollama configured to bind to `0.0.0.0` via systemd override
- [ ] Ollama enabled to start on boot (`systemctl enable ollama`)
- [ ] `embeddinggemma` model created and listed in `ollama list`
- [ ] Embedding test returns valid float array
- [ ] Port 11434 is NOT exposed in UFW firewall
- [ ] `docker-compose.yml` has `extra_hosts: host.docker.internal:host-gateway`
- [ ] `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`

---

## 🐳 Phase 1: Containerization

### Step 1.1: Backend Dockerfile

Create `backend/Dockerfile`:

```dockerfile
# Backend Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Run FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 1.2: Frontend Dockerfile

Create `frontend/Dockerfile`:

```dockerfile
# Frontend Build Stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build Next.js
RUN npm run build

# Production Stage
FROM node:20-alpine

WORKDIR /app

# Install production dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy built application from builder
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public

# Create non-root user
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001
USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:3000 || exit 1

CMD ["npm", "start"]
```

### Step 1.3: Docker Compose Configuration

Create `docker-compose.yml` in project root:

```yaml
version: "3.8"

services:
  backend:
    image: your_dockerhub_username/equilibrium-backend:latest
    container_name: equilibrium-backend
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
      - GROQ_API_KEY=${GROQ_API_KEY}
      - JWT_SECRET=${JWT_SECRET}
      - DATABASE_URL=${DATABASE_URL}
      - ADMIN_EMAIL=${ADMIN_EMAIL}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
    volumes:
      - ./backend/FAISS_Index:/app/FAISS_Index
      - ./backend/uploaded_docs:/app/uploaded_docs
      - ./backend/temp_uploaded_docs:/app/temp_uploaded_docs
    networks:
      - equilibrium-network
    restart: unless-stopped
    depends_on:
      - nginx

  frontend:
    image: your_dockerhub_username/equilibrium-frontend:latest
    container_name: equilibrium-frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
      - NODE_ENV=production
    networks:
      - equilibrium-network
    restart: unless-stopped
    depends_on:
      - nginx

  nginx:
    image: nginx:alpine
    container_name: equilibrium-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    networks:
      - equilibrium-network
    restart: unless-stopped

networks:
  equilibrium-network:
    driver: bridge

volumes:
  faiss-data:
  uploaded-docs:
```

### Step 1.4: Nginx Configuration

Create `nginx.conf`:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:3000;
    }

    # Redirect HTTP to HTTPS (optional, enable after SSL setup)
    # server {
    #     listen 80;
    #     server_name _;
    #     return 301 https://$host$request_uri;
    # }

    server {
        listen 80;
        server_name _;
        client_max_body_size 100M;

        # Frontend routes
        location / {
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
        }

        # Backend API routes
        location /api/ {
            proxy_pass http://backend/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://backend/health;
            access_log off;
        }
    }

    # HTTPS configuration (uncomment after SSL setup)
    # server {
    #     listen 443 ssl http2;
    #     server_name yourdomain.com;
    #
    #     ssl_certificate /etc/nginx/ssl/cert.pem;
    #     ssl_certificate_key /etc/nginx/ssl/key.pem;
    #     ssl_protocols TLSv1.2 TLSv1.3;
    #     ssl_ciphers HIGH:!aNULL:!MD5;
    #
    #     # ... rest of configuration
    # }
}
```

### Step 1.5: Environment Files

Create `.env.production` in project root:

```bash
# Backend
ENVIRONMENT=production
GROQ_API_KEY=your_groq_key_here
AUTH_SECRET=generate_secure_random_string_here
DATABASE_URL=postgresql://user:pass@your-neon-host/neondb?sslmode=require
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change_this_secure_password

# Ollama — runs on the VPS host, not inside Docker
# On Linux VPS with Docker extra_hosts, use:
OLLAMA_BASE_URL=http://host.docker.internal:11434

# Frontend
NEXT_PUBLIC_API_BASE=/api
NEXT_PUBLIC_API_BASE=https://yourdomain.com
```

> ⚠️ **Critical**: `OLLAMA_BASE_URL` must point to `http://host.docker.internal:11434` so the backend container can reach Ollama running on the VPS host. The `extra_hosts: host.docker.internal:host-gateway` entry in `docker-compose.yml` makes this work on Linux.

---

## 🚀 Phase 2: CI/CD Pipeline

### Step 2.1: GitHub Actions Workflow

**Prerequisites**: Add the following secrets to your GitHub repository (Settings -> Secrets and variables -> Actions):

- `DOCKER_USERNAME`: Your Docker Hub username
- `DOCKER_PASSWORD`: Your Docker Hub password or access token
- `VPS_HOST`: Your VPS IP address
- `VPS_USERNAME`: SSH username (e.g., `root` or `deploy`)
- `VPS_SSH_KEY`: Your private SSH key

Create `.github/workflows/deploy.yml`:

```yaml
name: Build and Test

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  backend-test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        working-directory: ./backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt pytest

      - name: Lint with flake8
        working-directory: ./backend
        run: |
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics || true

      - name: Test API
        working-directory: ./backend
        run: |
          pytest test_api.py -v || true

  frontend-build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: "frontend/package-lock.json"

      - name: Install dependencies
        working-directory: ./frontend
        run: npm ci

      - name: Lint
        working-directory: ./frontend
        run: npm run lint || true

      - name: Build
        working-directory: ./frontend
        run: npm run build

  docker-build:
    runs-on: ubuntu-latest
    needs: [backend-test, frontend-build]

    steps:
      - uses: actions/checkout@v3

      - name: Log in to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2

      - name: Build and Push Backend Docker Image
        uses: docker/build-push-action@v4
        with:
          context: ./backend
          push: true
          tags: ${{ secrets.DOCKER_USERNAME }}/equilibrium-backend:latest

      - name: Build and Push Frontend Docker Image
        uses: docker/build-push-action@v4
        with:
          context: ./frontend
          push: true
          tags: ${{ secrets.DOCKER_USERNAME }}/equilibrium-frontend:latest
          build-args: |
            NEXT_PUBLIC_API_BASE=/api

  deploy:
    runs-on: ubuntu-latest
    needs: docker-build

    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USERNAME }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/equilibrium
            docker-compose pull
            docker-compose up -d
```

### Step 2.2: Pre-deployment Checklist Script

Create `scripts/pre-deploy-check.sh`:

```bash
#!/bin/bash

echo "🔍 Pre-Deployment Checklist"
echo "============================"

# Check backend requirements
echo "✓ Checking backend..."
cd backend
if pip check -q 2>/dev/null; then
    echo "  ✅ Python dependencies OK"
else
    echo "  ⚠️  Warning: Dependency issues detected"
fi
cd ..

# Check frontend build
echo "✓ Checking frontend..."
cd frontend
if npm run build > /dev/null 2>&1; then
    echo "  ✅ Next.js build successful"
else
    echo "  ❌ Next.js build failed"
    exit 1
fi
cd ..

# Check Docker
echo "✓ Checking Docker..."
if command -v docker &> /dev/null; then
    echo "  ✅ Docker installed"
else
    echo "  ❌ Docker not found"
    exit 1
fi

if command -v docker-compose &> /dev/null; then
    echo "  ✅ Docker Compose installed"
else
    echo "  ❌ Docker Compose not found"
    exit 1
fi

# Check environment files
echo "✓ Checking environment files..."
if [ -f ".env.production" ]; then
    echo "  ✅ .env.production exists"
else
    echo "  ⚠️  .env.production missing (create before deploying)"
fi

echo ""
echo "✅ Pre-deployment checks complete!"
```

---

## 📦 Phase 3: Deployment

### Step 3.1: VPS Setup (DigitalOcean/Linode)

**Recommended**: Ubuntu 22.04 LTS, 1GB RAM, 25GB SSD (~$5-6/month)

```bash
# SSH into your VPS as root
ssh root@your_vps_ip

# Update system
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create application directory
mkdir -p /opt/equilibrium
cd /opt/equilibrium

# Create non-root user for app
useradd -m -s /bin/bash deploy
usermod -aG docker deploy

# Set permissions
chown -R deploy:deploy /opt/equilibrium
```

### Step 3.2: Deploy Application

```bash
# Clone repository (or use your preferred method)
cd /opt/equilibrium
git clone https://github.com/your-repo/pership-chatbot.git .

# Copy and configure environment file
cp .env.production.example .env.production
nano .env.production  # Edit with your actual values

# Build and start containers
docker-compose up -d

# Verify services are running
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Step 3.3: SSL Setup (Let's Encrypt)

```bash
# Install Certbot
apt-get install certbot python3-certbot-nginx -y

# Generate certificate (replace domain)
certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Update nginx.conf with SSL configuration
# Copy cert paths: /etc/letsencrypt/live/yourdomain.com/

# Restart Nginx
docker-compose restart nginx

# Setup auto-renewal
certbot renew --dry-run  # Test
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | crontab -
```

### Step 3.4: Firewall Configuration

```bash
# Enable UFW firewall
ufw enable

# Allow SSH (important - do this first!)
ufw allow 22/tcp

# Allow HTTP/HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Check status
ufw status
```

---

## 📋 Phase 4: Post-Deployment

### Step 4.1: Verification

```bash
# Health checks
curl http://yourdomain.com/health
curl http://yourdomain.com/api/health

# Test API endpoints
curl -X GET http://yourdomain.com/api/users

# Check logs for errors
docker-compose logs backend
docker-compose logs frontend
```

### Step 4.2: Backup Strategy

```bash
# Create backup script: scripts/backup.sh
#!/bin/bash
BACKUP_DIR="/backups/equilibrium-$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

# Backup FAISS index
docker run --rm -v equilibrium-backend:/app \
  -v $BACKUP_DIR:/backup \
  alpine cp -r /app/FAISS_Index /backup/

# Backup uploaded documents
docker run --rm -v equilibrium-backend:/app \
  -v $BACKUP_DIR:/backup \
  alpine cp -r /app/uploaded_docs /backup/

# Backup database (if using one)
# pg_dump ...

echo "Backup completed to $BACKUP_DIR"
```

**Setup automated daily backups**:

```bash
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/equilibrium/scripts/backup.sh") | crontab -
```

### Step 4.3: Monitoring

**Basic monitoring checklist**:

- [ ] Set up disk space alerts
- [ ] Monitor container restart counts
- [ ] Check application logs regularly
- [ ] Test health endpoints daily

```bash
# Simple monitoring script
#!/bin/bash
while true; do
  STATUS=$(docker-compose ps | grep -c "Up")
  if [ $STATUS -ne 3 ]; then
    echo "⚠️ Warning: Not all containers running!"
    docker-compose ps
  fi
  sleep 300
done
```

### Step 4.4: Maintenance

**Weekly**:

- [ ] Review application logs
- [ ] Verify backups completed
- [ ] Check disk usage

**Monthly**:

- [ ] Update dependencies (test in dev first)
- [ ] Review security logs
- [ ] Test disaster recovery

---

## 💰 Cost Breakdown

| Item                      | Cost/Month  | Notes                                                               |
| ------------------------- | ----------- | ------------------------------------------------------------------- |
| VPS (Linode/DigitalOcean) | **$12-18**  | **2GB RAM min** required for Ollama + all services. 4GB recommended |
| Domain (optional)         | $0-1        | Domains typically ~$10/year                                         |
| SSL Certificate           | $0          | Let's Encrypt (free)                                                |
| Neon PostgreSQL           | $0-19       | Free tier (0.5GB) covers <100 users; paid for more                  |
| Backups                   | $0-2        | Offsite backup storage                                              |
| **Total**                 | **~$12-20** | Includes local Ollama inference (no OpenAI/Groq embedding cost)     |

> ⚠️ **VPS RAM Warning**: Ollama running `embeddinggemma` needs ~1-2GB RAM on top of your app services. A **1GB VPS will OOM (out-of-memory crash)**. Use at least 2GB RAM VPS.

**Scaling upgrades**:

- Recommended start: **4GB RAM, 2 vCPU** VPS (~$18-24/month) for comfortable headroom
- If you hit 500 users: Upgrade to 8GB RAM ($36-48/month)
- If you hit 2000 users: Consider separate Ollama server + load balancer

---

## 🔧 Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs backend
docker-compose logs frontend

# Rebuild containers
docker-compose down
docker-compose build --no-cache
docker-compose up
```

### Out of disk space

```bash
# Check usage
df -h
du -sh /var/lib/docker

# Clean up
docker system prune -a  # ⚠️ Warning: removes unused images
docker volume prune
```

### Backend API not responding

```bash
# Check if backend container is running
docker-compose ps backend

# Restart backend
docker-compose restart backend

# Verify ports
netstat -tlnp | grep 8000

# Test connection inside container
docker-compose exec backend curl http://localhost:8000/health
```

### Frontend showing blank page

```bash
# Verify environment variable
docker-compose exec frontend echo $NEXT_PUBLIC_API_BASE

# Check browser console for errors
# Inspect nginx logs
docker-compose logs nginx
```

### SSL certificate issues

```bash
# Verify certificate
openssl x509 -in /etc/letsencrypt/live/yourdomain.com/fullchain.pem -text -noout

# Check renewal
certbot certificates

# Manual renewal
certbot renew --force-renewal
```

### Ollama not reachable from backend container

```bash
# Verify Ollama is running on host
systemctl status ollama

# Test from inside the backend container
docker-compose exec backend curl http://host.docker.internal:11434/api/tags

# If that fails, verify extra_hosts is set in docker-compose.yml:
# extra_hosts:
#   - "host.docker.internal:host-gateway"

# Check Ollama is binding to 0.0.0.0 (not just 127.0.0.1)
ss -tlnp | grep 11434
# If only 127.0.0.1:11434 shows, edit Ollama systemd override:
sudo systemctl edit ollama
# Add:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0"
sudo systemctl restart ollama
```

### embeddinggemma model not found

```bash
# List available models
ollama list

# If embeddinggemma is missing, recreate it from the Modelfile
ollama create embeddinggemma -f /opt/equilibrium/Modelfile.embeddinggemma

# Verify model works
curl http://localhost:11434/api/embeddings \
  -d '{"model": "embeddinggemma", "prompt": "test"}'
```

### Ollama OOM / VPS out of memory

```bash
# Check memory usage
free -h

# Check Ollama memory usage
ps aux | grep ollama

# Add swap if needed (emergency fix for small VPS)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
# Make permanent:
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Long-term fix: upgrade VPS RAM
```

---

## 📚 Quick Commands

```bash
# Start application
docker-compose up -d

# Stop application
docker-compose down

# View logs (all services)
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend

# SSH into backend container
docker-compose exec backend /bin/bash

# Restart a service
docker-compose restart backend

# Rebuild without cache
docker-compose build --no-cache

# Pull latest images
docker-compose pull

# Clean up unused resources
docker system prune -a --volumes
```

---

## ⚠️ Important Security Reminders

✅ **DO**:

- [ ] Use strong JWT secrets (generate with: `openssl rand -base64 32`)
- [ ] Rotate admin credentials regularly
- [ ] Keep Docker and OS updated
- [ ] Monitor access logs
- [ ] Backup data regularly
- [ ] Use HTTPS in production

❌ **DON'T**:

- [ ] Commit `.env.production` to Git
- [ ] Expose Docker daemon publicly
- [ ] Use default passwords
- [ ] Disable firewall
- [ ] Run containers as root
- [ ] Ignore security updates

---

## 📞 Next Steps

1. **Immediate** (This week):
   - [ ] Create Docker files and docker-compose.yml
   - [ ] Test build locally
   - [ ] Verify all dependencies in Dockerfile
   - [ ] **Test Ollama + embeddinggemma locally** (`ollama create embeddinggemma -f Modelfile`)

2. **Short-term** (Next 2 weeks):
   - [ ] Provision VPS (**2GB RAM minimum**, 4GB recommended)
   - [ ] **Install Ollama on VPS and pull embeddinggemma model** (Phase 0)
   - [ ] Set up GitHub Actions CI/CD
   - [ ] Deploy to staging
   - [ ] Test all API endpoints including RAG/embedding

3. **Medium-term** (Next month):
   - [ ] Set up SSL/HTTPS
   - [ ] Configure automated backups (including FAISS index)
   - [ ] Performance testing (load test with Ollama embedding)
   - [ ] Production go-live

---

**Last Updated**: 2026-06-25  
**Status**: Updated — Ollama/Gemma VPS deployment section added
