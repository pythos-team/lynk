```markdown
# Deployment

Lynkio is designed to be easy to deploy. Because it has no external dependencies, you can run it on any machine with Python 3.7+.

## Running with Python Directly

The simplest way is to run your application script:

```bash
python app.py
```

This starts the server in the foreground. For production, you'll want to run it as a background process or use a process manager.

## Using the CLI

Lynk includes a simple CLI that lets you run an application module directly:

```bash
python -m lynkio myapp:app --host 0.0.0.0 --port 8765 --debug
```

The format is module:variable, where variable is the Lynkio instance.

## Process Managers

## systemd (Linux)

Create a systemd service file /etc/systemd/system/lynk.service:

```ini
[Unit]
Description=Lynk Application
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/app
ExecStart=/usr/bin/python3 /path/to/app/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl enable lynk
sudo systemctl start lynk
```

## Supervisor

Install supervisor and create a config /etc/supervisor/conf.d/lynk.conf:

```ini
[program:lynk]
command=/usr/bin/python3 /path/to/app/app.py
directory=/path/to/app
user=youruser
autostart=true
autorestart=true
stderr_logfile=/var/log/lynk.err.log
stdout_logfile=/var/log/lynk.out.log
```

Then reload supervisor:

```bash
supervisorctl reread
supervisorctl update
```

## Reverse Proxy (Nginx)

For production, it's common to put Lynk behind a reverse proxy like Nginx to handle SSL, load balancing, and static files.

Example Nginx config:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

For WebSocket support, the Upgrade and Connection headers must be passed correctly.

SSL / HTTPS

Lynkio itself does not handle SSL. Use a reverse proxy (Nginx, Caddy, HAProxy) to terminate SSL.

Load Balancing

You can run multiple Lynkio instances behind a load balancer. However, note that rooms and client sessions are stored in‑memory and are not shared across instances. If you need horizontal scaling, consider using an external pub/sub (like Redis or built-in Database) – though Lynkio doesn't provide that out of the box.

## Database Backups

If you use soketDB for logging, configure automatic backups in the database_config. See the soketDB documentation for details on cloud backup providers.

## Cloud providers

cloud providers Lynkio supports

```text
huggingface,
google_drive,
aws,
dropbox
```

Next

· Understand the internal architecture: Architecture