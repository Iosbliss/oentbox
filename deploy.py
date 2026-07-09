"""
OentBox VPS Deploy Script (Python + paramiko)
Deploys the Docker project to a Linux VPS non-interactively.
"""
import os, sys, io, tarfile, fnmatch, time, paramiko, scp as scp_mod

VPS_IP   = os.environ.get("VPS_IP", "199.246.88.46")
VPS_USER = os.environ.get("VPS_USER", "root")
VPS_PASS = os.environ.get("VPS_PASS", "ovCzH77rqAq4i8rPs5ED")
REMOTE_DIR = "/opt/oentbox"
PROJECT = "oentbox"

EXCLUDES = [
    "__pycache__", "*.pyc", "*.pyo", "db.sqlite3", "db.sqlite3-journal",
    ".git", ".venv", "venv", "env", "node_modules", "*.tar.gz", "*.log",
    ".env", ".env.local", "deploy.ps1", "deploy.py",
]

def excluded(name):
    base = os.path.basename(name)
    for pat in EXCLUDES:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(base, pat):
            return True
    return False

def ssh_connect():
    print(f"[1/6] Connecting to {VPS_USER}@{VPS_IP}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_IP, username=VPS_USER, password=VPS_PASS, timeout=15)
    print("       SSH connected.")
    return client

def run_remote(client, cmd, check=True):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    for line in out.splitlines():
        try:
            print(f"       {line}")
        except UnicodeEncodeError:
            print(f"       {line.encode('ascii', errors='replace').decode()}")
    if err and "WARNING: Image" not in err:
        for line in err.splitlines():
            try:
                print(f"       [stderr] {line}")
            except UnicodeEncodeError:
                print(f"       [stderr] {line.encode('ascii', errors='replace').decode()}")
    if check and stdout.channel.recv_exit_status() != 0:
        raise RuntimeError(f"Command failed: {cmd}\nstderr: {err}")
    return out

def install_docker(client):
    print("\n[2/6] Installing Docker & Docker Compose...")
    script = """
set -e
if ! command -v docker >/dev/null 2>&1; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "Docker already installed: $(docker --version)"
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Installing Docker Compose plugin..."
    apt-get update -qq
    apt-get install -y -qq docker-compose-plugin
else
    echo "Docker Compose already: $(docker compose version)"
fi
"""
    run_remote(client, script)

def bundle_project():
    print("\n[3/6] Bundling project files...")
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "venv", "env", "node_modules", "__pycache__")]
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, ".")
                rel = rel.replace(os.sep, "/")
                if excluded(rel):
                    continue
                tar.add(fp, arcname=rel)
                count += 1
    buf.seek(0)
    size_mb = len(buf.getbuffer()) / (1024*1024)
    print(f"       Packed {count} files ({size_mb:.1f} MB)")
    return buf

def upload_and_extract(client, tarbuf):
    print("\n[4/6] Uploading to VPS...")
    run_remote(client, f"mkdir -p {REMOTE_DIR}")
    # Use SFTP to upload the tarball
    sftp = client.open_sftp()
    sftp.putfo(tarbuf, f"{REMOTE_DIR}/deploy.tar.gz")
    sftp.close()
    print(f"       Uploaded. Extracting...")
    run_remote(client, f"cd {REMOTE_DIR} && tar -xzf deploy.tar.gz && rm -f deploy.tar.gz")
    print("       Extracted.")

def configure_env(client):
    print("\n[5/6] Configuring .env on VPS...")
    run_remote(client, f"""
cd {REMOTE_DIR}
if [ ! -f .env ]; then
    echo 'Creating .env from .env.example...'
    cp .env.example .env
fi

# Auto-generate SECRET_KEY if placeholder
if grep -q 'change-me-to-a-random-50-char-string' .env 2>/dev/null; then
    NEW_KEY=$(openssl rand -hex 32)
    sed -i "s/change-me-to-a-random-50-char-string/$NEW_KEY/" .env
    echo 'Generated DJANGO_SECRET_KEY.'
fi

# Auto-generate DB_PASSWORD if placeholder
if grep -q 'change-me-strong-db-password' .env 2>/dev/null; then
    NEW_PW=$(openssl rand -hex 16)
    sed -i "s/change-me-strong-db-password/$NEW_PW/" .env
    echo 'Generated DB_PASSWORD.'
fi

# Set ALLOWED_HOSTS and DOMAIN to the VPS IP
sed -i 's|your-domain.com,www.your-domain.com|{VPS_IP}|' .env
sed -i 's|^DOMAIN=.*|DOMAIN={VPS_IP}|' .env
echo 'Configured ALLOWED_HOSTS and DOMAIN to {VPS_IP}.'
""")

def build_and_launch(client):
    print("\n[6/6] Building and launching containers...")
    run_remote(client, f"""
set -e
cd {REMOTE_DIR}
echo 'Building Docker image...'
docker compose build 2>&1 | tail -30
echo 'Starting services...'
docker compose up -d
echo 'Waiting for Postgres...'
for i in $(seq 1 20); do
    if docker compose exec -T db pg_isready -U oentbox >/dev/null 2>&1; then
        echo 'Postgres ready.'
        break
    fi
    sleep 2
done
echo 'Waiting for Django...'
for i in $(seq 1 40); do
    if docker compose exec -T django curl -sf http://localhost:8000/ >/dev/null 2>&1; then
        echo 'Django ready.'
        break
    fi
    sleep 3
done
echo ''
echo 'Container status:'
docker compose ps
""")

def main():
    print("=" * 50)
    print("  OentBox Docker Deploy")
    print(f"  Target: {VPS_USER}@{VPS_IP}:{REMOTE_DIR}")
    print("=" * 50)

    client = ssh_connect()
    try:
        install_docker(client)
        tarbuf = bundle_project()
        upload_and_extract(client, tarbuf)
        configure_env(client)
        build_and_launch(client)

        print()
        print("=" * 50)
        print("  Deploy complete!")
        print(f"  Site: http://{VPS_IP}")
        print("=" * 50)
        print()
        print("Post-deploy:")
        print(f"  1. Open http://{VPS_IP} in your browser")
        print(f"  2. Create admin:  docker compose exec django python manage.py createsuperuser")
        print(f"  3. View logs:    docker compose logs -f")
        print()
    finally:
        client.close()

if __name__ == "__main__":
    main()
