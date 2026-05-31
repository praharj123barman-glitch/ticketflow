# Deployment

TicketFlow runs as a single self-hosted Dockerized stack on one AWS EC2 VM.
nginx terminates TLS, serves the React build at `/`, and reverse-proxies the API
under `/api/*` to gunicorn — so the whole app lives on **one HTTPS origin**.

```
Browser ─HTTPS─▶ nginx (EC2)
                  ├── /        → React static build
                  └── /api/*   → gunicorn/uvicorn → FastAPI → Postgres + Redis
```

## Live URLs
- **App + API (one origin):** https://ticketflow-prohorj.duckdns.org
- **Swagger docs:** https://ticketflow-prohorj.duckdns.org/api/docs
- Demo login: `demo@ticketflow.dev` / `password123`

## 1. AWS EC2 (Ubuntu 24.04, t3.small)
Security group inbound: 22 (SSH), 80 (HTTP), 443 (HTTPS). An **Elastic IP** is
attached so the address survives stop/start.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
git clone https://github.com/praharj123barman-glitch/ticketflow.git && cd ticketflow
echo "JWT_SECRET=$(openssl rand -hex 32)" > .env
sudo docker compose up -d --build      # entrypoint runs `alembic upgrade head` then gunicorn
sudo docker compose exec api python seed.py
```

## 2. HTTPS (Let's Encrypt + nginx)
A free DuckDNS subdomain points at the Elastic IP. Issue the cert with certbot
(standalone; nginx briefly stopped for the HTTP-01 challenge):

```bash
sudo apt-get install -y certbot
sudo docker compose stop nginx
sudo certbot certonly --standalone -d <domain> --agree-tos -m <email> --non-interactive
```

**Auto-renewal** runs unattended via certbot renewal hooks that stop/start the
nginx container around renewal (`sudo certbot renew --dry-run` passes):
- `/etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh`  → `docker compose stop nginx`
- `/etc/letsencrypt/renewal-hooks/post/start-nginx.sh` → `docker compose start nginx`

## 3. Serve the frontend from nginx (single origin)
Build the SPA and have nginx serve it + proxy the API:

```bash
cd frontend && npm install && npm run build      # produces frontend/dist (calls /api)
cp ../deploy/nginx.prod.conf ../nginx/nginx.conf  # SPA at /, API at /api/*
cp ../deploy/docker-compose.override.yml ../docker-compose.override.yml
cd .. && sudo docker compose up -d                # opens 443, mounts certs + dist, sets ROOT_PATH=/api
```

- `ROOT_PATH=/api` makes FastAPI generate correct Swagger URLs behind the prefix.
- The SPA calls the API at the same origin (`/api/...`), so there is no CORS and
  no mixed content. See `deploy/` for the exact production config files.

## Operating notes
- **Keep the instance running** during placement season — `t3.small` on the
  $100 free-plan credits lasts ~6 months 24/7. Stopping it takes the live demo
  down (the Elastic IP keeps the same address on restart).
- Postgres/Redis ports are published on the VM for convenience but are blocked
  from the internet by the security group (only 22/80/443 are open).
