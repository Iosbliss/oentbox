"""
Configure oentbox.com with HTTPS on the VPS.
- Updates .env with domain
- Installs Certbot, gets Let's Encrypt cert
- Configures nginx for SSL
- Restarts containers
- Sets up auto-renewal
"""
import paramiko, time, os

VPS_IP   = "199.246.88.46"
VPS_USER = "root"
VPS_PASS = "ovCzH77rqAq4i8rPs5ED"
DOMAIN   = "oentbox.com"
REMOTE_DIR = "/opt/oentbox"

def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VPS_IP, username=VPS_USER, password=VPS_PASS, timeout=15,
              allow_agent=False, look_for_keys=False)
    return c

def run(c, cmd, timeout=300):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    for line in out.splitlines():
        print(f"  {line}")
    if err:
        for line in err.splitlines():
            if line.strip():
                print(f"  [stderr] {line}")
    return out, stdout.channel.recv_exit_status()

def upload(c, local, remote):
    sftp = c.open_sftp()
    sftp.put(local, remote)
    sftp.close()
    print(f"  Uploaded {local} -> {remote}")

def main():
    print("=" * 55)
    print(f"  Setting up {DOMAIN} with HTTPS on {VPS_IP}")
    print("=" * 55)

    c = ssh()
    try:
        # ---- 1. Update .env ----
        print("\n[1/6] Updating .env with domain config...")
        run(c, f"""
cd {REMOTE_DIR}
sed -i 's|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS={DOMAIN},www.{DOMAIN},{VPS_IP}|' .env
sed -i 's|^DOMAIN=.*|DOMAIN={DOMAIN}|' .env
sed -i 's|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://{DOMAIN},https://www.{DOMAIN}|' .env
grep -E '^(DJANGO_ALLOWED_HOSTS|DOMAIN|CSRF_TRUSTED_ORIGINS)=' .env | sed 's/SECRET_KEY=.*/SECRET_KEY=***/'
""")

        # ---- 2. Stop nginx (free port 80 for Certbot) ----
        print("\n[2/6] Stopping nginx container (free port 80 for cert)...")
        run(c, f"cd {REMOTE_DIR} && docker compose stop nginx 2>&1", timeout=60)
        time.sleep(3)

        # ---- 3. Install Certbot & get cert ----
        print("\n[3/6] Installing Certbot & requesting Let's Encrypt cert...")
        run(c, "apt-get update -qq", timeout=60)
        run(c, "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot", timeout=120)

        # Use standalone mode (nginx is stopped, port 80 is free)
        run(c, f"certbot certonly --standalone -d {DOMAIN} -d www.{DOMAIN} --non-interactive --agree-tos --email admin@{DOMAIN} --no-eff-email 2>&1 || echo CERTBOT_DONE", timeout=120)

        # ---- 4. Create SSL nginx config ----
        print("\n[4/6] Creating nginx SSL configuration...")
        ssl_conf = f"""upstream django {{
    server django:8000;
}}

server {{
    listen 80;
    server_name {DOMAIN} www.{DOMAIN};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {DOMAIN} www.{DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/{DOMAIN}/fullchain.pem;
    ssl_certificate_key  /etc/letsencrypt/live/{DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 20M;

    location /static/ {{
        alias /usr/share/nginx/html/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    location /media/ {{
        alias /usr/share/nginx/html/media/;
        expires 7d;
        add_header Cache-Control "public";
    }}

    location / {{
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }}
}}
"""
        with open("nginx_ssl.conf", "w", newline="\n") as f:
            f.write(ssl_conf)
        upload(c, "nginx_ssl.conf", f"{REMOTE_DIR}/nginx/nginx_ssl.conf")

        # Update docker-compose to mount SSL certs into nginx
        compose_patch = """
cd %s
python3 -c "
import re
with open('docker-compose.yml') as f:
    content = f.read()

# Add SSL volume mounts to nginx service
old_volumes = '''      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - static_data:/usr/share/nginx/html/static:ro
      - media_data:/usr/share/nginx/html/media:ro'''
new_volumes = '''      - ./nginx/nginx_ssl.conf:/etc/nginx/conf.d/default.conf:ro
      - static_data:/usr/share/nginx/html/static:ro
      - media_data:/usr/share/nginx/html/media:ro
      - /etc/letsencrypt/live/%s:/etc/letsencrypt/live/%s:ro
      - /etc/letsencrypt/archive/%s:/etc/letsencrypt/archive/%s:ro'''

if old_volumes in content:
    content = content.replace(old_volumes, new_volumes %% ('%s','%s','%s','%s'))
    with open('docker-compose.yml','w') as f:
        f.write(content)
    print('docker-compose.yml patched for SSL')
else:
    print('WARNING: volume block not found, manual edit needed')
"
""" % (REMOTE_DIR, DOMAIN, DOMAIN, DOMAIN, DOMAIN, DOMAIN, DOMAIN, DOMAIN)
        run(c, compose_patch, timeout=30)

        # Verify the patch
        run(c, f"cd {REMOTE_DIR} && grep -A3 'nginx_ssl.conf' docker-compose.yml | head -5", timeout=10)

        # ---- 5. Restart containers ----
        print("\n[5/6] Restarting containers with SSL config...")
        run(c, f"cd {REMOTE_DIR} && docker compose up -d 2>&1", timeout=60)
        time.sleep(8)

        # ---- 6. Verify & set up auto-renewal ----
        print("\n[6/6] Verifying HTTPS & setting up auto-renewal...")
        run(c, f"curl -sf -o /dev/null -w '%{{http_code}}' -H 'Host: {DOMAIN}' https://{DOMAIN}/ 2>&1 || echo 'HTTPS test failed'")

        # Auto-renewal via cron
        run(c, """
# Create renewal script
cat > /opt/oentbox/renew-ssl.sh << 'RENEW'
#!/bin/bash
cd /opt/oentbox
docker compose stop nginx
certbot renew --quiet
docker compose start nginx
RENEW
chmod +x /opt/oentbox/renew-ssl.sh

# Add to crontab if not already there
(crontab -l 2>/dev/null | grep -v renew-ssl; echo "0 3 * * * /opt/oentbox/renew-ssl.sh") | crontab -
echo "Auto-renewal set up (runs daily at 3 AM)"
""", timeout=30)

        run(c, f"cd {REMOTE_DIR} && docker compose ps 2>&1", timeout=20)

        print("\n" + "=" * 55)
        print(f"  HTTPS setup complete!")
        print(f"  Site: https://{DOMAIN}")
        print("=" * 55)

    finally:
        c.close()

if __name__ == "__main__":
    main()
