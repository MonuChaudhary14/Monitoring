# Monitoring Project

A Django-based infrastructure monitoring project with:

- server registration
- metric ingestion for CPU, memory, and disk usage
- websocket-based live dashboard updates
- alert generation for sustained high CPU
- API activity logging with request IP visibility
- a lightweight Python agent for pushing host metrics

This README focuses on getting the project running cleanly on an AWS EC2 instance.

## Project Layout

- `observability/` Django project and monitoring app
- `agent/agent.py` metric collection agent
- `requirements.txt` Python dependencies

## Features

- Register monitored servers through `/api/register/`
- Push infrastructure metrics through `/api/ingest/`
- View charts and alerts in `/api/dashboard/`
- See recent API hits, endpoints, and IP addresses in the dashboard
- Track server status as online or offline

## Tech Stack

- Python
- Django
- Django REST Framework
- Django Channels
- Redis
- Celery
- PostgreSQL or SQLite for local fallback
- Chart.js

## Recommended EC2 Setup

This guide assumes:

- Ubuntu 22.04 or 24.04 EC2
- one EC2 instance for the app
- Redis installed on the same instance
- PostgreSQL either on the same instance or on Amazon RDS
- Nginx as reverse proxy
- Daphne as the ASGI app server
- Celery worker running as a background service

## 1. Launch the EC2 Instance

Recommended instance for a small demo:

- `t3.small` or `t3.medium`

Security group:

- allow `22` from your IP
- allow `80` from the internet
- allow `443` from the internet if you plan to add HTTPS

If PostgreSQL is on another machine or RDS:

- allow the PostgreSQL port `5432` between the app host and database

## 2. SSH Into the Instance

```bash
ssh -i /path/to/key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

## 3. Install System Packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx redis-server postgresql-client libpq-dev build-essential
```

Enable Redis and Nginx:

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
sudo systemctl enable nginx
sudo systemctl start nginx
```

## 4. Clone the Repository

Choose an app directory:

```bash
sudo mkdir -p /srv/monitoring
sudo chown ubuntu:ubuntu /srv/monitoring
cd /srv/monitoring
git clone <YOUR_REPOSITORY_URL> .
```

## 5. Create the Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Create the Environment File

Create `observability/.env`:

```env
SECRET_KEY=replace-with-a-long-random-secret
DEBUG=False
ALLOWED_HOSTS=YOUR_EC2_PUBLIC_IP,YOUR_DOMAIN,localhost,127.0.0.1

DB_ENGINE=django.db.backends.postgresql
DB_NAME=observability_db
DB_USER=observability_user
DB_PASSWORD=replace-with-db-password
DB_HOST=127.0.0.1
DB_PORT=5432

REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-password
```

Notes:

- `ALLOWED_HOSTS` should include your EC2 public IP and domain if you use one.
- If you do not want PostgreSQL immediately, you can omit the `DB_*` values and Django will fall back to SQLite.
- For production, PostgreSQL is strongly recommended.

## 7. Prepare PostgreSQL

If you are using PostgreSQL, create the database and user first.

Example:

```sql
CREATE DATABASE observability_db;
CREATE USER observability_user WITH PASSWORD 'replace-with-db-password';
GRANT ALL PRIVILEGES ON DATABASE observability_db TO observability_user;
```

If you use Amazon RDS instead:

- create a PostgreSQL RDS instance
- allow access from the EC2 security group
- set `DB_HOST` to the RDS endpoint

## 8. Run Migrations

```bash
cd /srv/monitoring
source venv/bin/activate
python observability/manage.py migrate
```

Optional admin user:

```bash
python observability/manage.py createsuperuser
```

Collect static files:

```bash
python observability/manage.py collectstatic --noinput
```

## 9. Test the App Manually

Start Daphne:

```bash
cd /srv/monitoring
source venv/bin/activate
daphne -b 0.0.0.0 -p 8001 observability.asgi:application
```

If import resolution fails, run it from the Django project directory:

```bash
cd /srv/monitoring/observability
source ../venv/bin/activate
daphne -b 0.0.0.0 -p 8001 observability.asgi:application
```

Then open:

- `http://YOUR_EC2_PUBLIC_IP/api/dashboard/`

## 10. Create Systemd Service for Daphne

Create `/etc/systemd/system/monitoring-daphne.service`:

```ini
[Unit]
Description=Monitoring Daphne Service
After=network.target redis-server.service

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/srv/monitoring/observability
Environment="DJANGO_SETTINGS_MODULE=observability.settings"
ExecStart=/srv/monitoring/venv/bin/daphne -b 127.0.0.1 -p 8001 observability.asgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable monitoring-daphne
sudo systemctl start monitoring-daphne
sudo systemctl status monitoring-daphne
```

## 11. Create Systemd Service for Celery

Create `/etc/systemd/system/monitoring-celery.service`:

```ini
[Unit]
Description=Monitoring Celery Worker
After=network.target redis-server.service

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/srv/monitoring/observability
Environment="DJANGO_SETTINGS_MODULE=observability.settings"
ExecStart=/srv/monitoring/venv/bin/celery -A observability worker --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable monitoring-celery
sudo systemctl start monitoring-celery
sudo systemctl status monitoring-celery
```

Note:

- The project contains a Celery task file, but no periodic beat schedule is configured in code yet.
- If you later add scheduled tasks, also create a `celery beat` service.

## 12. Configure Nginx

Create `/etc/nginx/sites-available/monitoring`:

```nginx
server {
    listen 80;
    server_name YOUR_EC2_PUBLIC_IP YOUR_DOMAIN;

    location /static/ {
        alias /srv/monitoring/observability/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/monitoring /etc/nginx/sites-enabled/monitoring
sudo nginx -t
sudo systemctl reload nginx
```

Remove the default site if needed:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl reload nginx
```

## 13. Open the Dashboard

Once Nginx and Daphne are running:

- `http://YOUR_EC2_PUBLIC_IP/api/dashboard/`

You should see:

- system summary cards
- server selector
- metric charts
- alert history
- API hit summary with IP addresses
- recent API activity table

## 14. Run the Agent

The agent can run on the same EC2 instance or on another machine.

Before running the agent, update `agent/agent.py`:

```python
URL_BASE = "http://YOUR_EC2_PUBLIC_IP/api"
```

Then run:

```bash
cd /srv/monitoring
source venv/bin/activate
python agent/agent.py
```

What the agent does:

- registers the server if no API key exists locally
- stores the API key in `api_key.txt`
- sends CPU, memory, and disk usage every 5 seconds

## 15. Useful Health Checks

Check Django:

```bash
cd /srv/monitoring
source venv/bin/activate
python observability/manage.py check
```

Check tests:

```bash
python observability/manage.py test monitoring --settings=observability.test_settings
```

Check services:

```bash
sudo systemctl status monitoring-daphne
sudo systemctl status monitoring-celery
sudo systemctl status nginx
sudo systemctl status redis-server
```

Check logs:

```bash
journalctl -u monitoring-daphne -f
journalctl -u monitoring-celery -f
sudo tail -f /var/log/nginx/error.log
```

## Alternative Setup: Cloudflare Tunnel (No Nginx)

If you are using a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (using `cloudflared`) to expose your server via a subdomain (e.g., `server.example.com`), you can completely skip the Nginx configuration.

1. **Skip Nginx**: Do not install or configure Nginx (Skip Step 12).
2. **Run Daphne**: Set up the Daphne systemd service exactly as shown in Step 10, ensuring it runs on a local port like `8001`.
3. **Configure Tunnel**: In your Cloudflare Zero Trust dashboard (or `cloudflared` config), create a Public Hostname routing your subdomain to `http://127.0.0.1:8001`. Cloudflare Tunnel supports WebSockets natively, so the real-time dashboard updates (Django Channels) will work out of the box.
4. **Update `.env`**: Ensure your subdomain is included in the `ALLOWED_HOSTS` list in your `observability/.env` file.
   ```env
   ALLOWED_HOSTS=server.example.com,127.0.0.1,localhost
   ```
5. **CSRF Settings (If Needed)**: If you encounter `403 CSRF verification failed` errors when submitting forms (because Cloudflare provides HTTPS but proxies HTTP to your server), add the following to `observability/observability/settings.py`:
   ```python
   CSRF_TRUSTED_ORIGINS = ['https://server.example.com']
   SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
   ```

## 16. Recommended Next Production Improvements

This project now works well as an EC2-hosted MVP, but for stronger production readiness you should still add:

- HTTPS with Let’s Encrypt
- database backups
- a proper domain name
- stricter dashboard/API authentication
- log rotation and centralized monitoring
- alert notification channels like email, Slack, or SMS
- metric retention cleanup for old `InfrastructureMetric` and `APIRequestLog` rows

## Troubleshooting

### Dashboard not loading

Check:

- `ALLOWED_HOSTS`
- Nginx config
- Daphne service status
- whether port `80` is open in the EC2 security group

### Websocket updates not working

Check:

- Redis is running
- `REDIS_URL` is set
- Nginx includes `Upgrade` and `Connection` headers
- Daphne is running successfully

### Static files not showing

Run:

```bash
cd /srv/monitoring
source venv/bin/activate
python observability/manage.py collectstatic --noinput
```

Then reload Nginx.

### Database connection errors

Check:

- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`
- PostgreSQL or RDS security group rules
- local firewall rules if using self-hosted PostgreSQL

## Local Development Quick Start

```bash
git clone <YOUR_REPOSITORY_URL>
cd Monitoring
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp observability/.env observability/.env.local.backup
python observability/manage.py migrate
python observability/manage.py runserver
```

Open:

- `http://127.0.0.1:8000/api/dashboard/`

## API Endpoints

- `POST /api/register/`
- `POST /api/ingest/`
- `GET /api/metrics/?server=<id>&minutes=<n>`
- `GET /api/servers/`
- `GET /api/system-summary/`
- `GET /api/api-activity/`
- `GET /api/dashboard-data/?server=<id>&minutes=<n>`
- `GET /api/dashboard/`

## Current Status

This repository is now suitable for:

- local development
- project demonstration
- EC2 deployment for MVP use

It is not yet a fully hardened enterprise monitoring platform, but this README gives you a proper path to install and run it on AWS EC2 cleanly.
