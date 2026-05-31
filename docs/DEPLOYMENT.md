# Deployment

TicketFlow runs as a Dockerized stack on a single AWS EC2 VM, with the React
frontend on Vercel and HTTPS via Let's Encrypt.

```
Browser ─HTTPS─▶ Vercel (React static)  ─HTTPS calls─▶  ┐
                                                         │
Browser ─HTTPS─▶ nginx (TLS, EC2) ─▶ gunicorn/uvicorn ─▶ FastAPI ─▶ Postgres + Redis
```

## Live URLs
- **Frontend (Vercel):** https://frontend-seven-delta-18.vercel.app
- **API + Swagger docs:** https://ticketflow-prohorj.duckdns.org/docs
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
A free DuckDNS subdomain points at the Elastic IP. Certificate issued with
certbot (standalone, nginx briefly stopped for the HTTP-01 challenge):

```bash
sudo apt-get install -y certbot
sudo docker compose stop nginx
sudo certbot certonly --standalone -d <domain> --agree-tos -m <email> --non-interactive
```

HTTPS is enabled by a VM-only `docker-compose.override.yml` (opens 443, mounts
`/etc/letsencrypt`) plus an nginx server block that terminates TLS and redirects
HTTP→HTTPS. See `nginx/nginx.conf` (the commented 443 block is the template).

**Auto-renewal** works unattended via certbot renewal hooks that stop/start the
nginx container around renewal:
- `/etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh`  → `docker compose stop nginx`
- `/etc/letsencrypt/renewal-hooks/post/start-nginx.sh` → `docker compose start nginx`

(`sudo certbot renew --dry-run` passes.)

## 3. Frontend (Vercel)
Built with the live API baked in at build time:
```bash
cd frontend
vercel deploy --prod --build-env VITE_API_URL=https://<domain>
```
The FastAPI app sends permissive CORS headers, so the cross-origin Vercel → API
calls work; everything is HTTPS so there is no mixed-content blocking.

## Operating notes
- **Stop the instance when idle** to conserve credits; the Elastic IP keeps the
  same address on restart.
- Postgres/Redis ports are published on the VM for convenience but are blocked
  from the internet by the security group (only 22/80/443 are open).
