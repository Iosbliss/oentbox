#!/bin/bash
set -e

# ==========================================================
#  OentBox VPS Deploy Script
#  One-command Docker deployment to a Linux VPS
#  Usage: ./deploy.sh your-vps-ip
# ==========================================================

VPS_IP="${1:?Usage: ./deploy.sh <vps-ip>}"
VPS_USER="${2:-root}"
PROJECT="oentbox"
REMOTE_DIR="/opt/${PROJECT}"

echo ""
echo "========================================="
echo "  OentBox Docker Deploy"
echo "  Target: ${VPS_USER}@${VPS_IP}:${REMOTE_DIR}"
echo "========================================="
echo ""

# ---------- Step 1: check SSH ----------
echo "[1/6] Checking SSH connection..."
if ! ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "${VPS_USER}@${VPS_IP}" "echo ok" &>/dev/null; then
    echo "ERROR: Cannot SSH to ${VPS_USER}@${VPS_IP}. Check your key/credentials."
    exit 1
fi
echo "       SSH OK."

# ---------- Step 2: install Docker on VPS ----------
echo "[2/6] Installing Docker & Docker Compose on VPS (if missing)..."
ssh "${VPS_USER}@${VPS_IP}" '
    set -e
    if ! command -v docker &>/dev/null; then
        echo "       Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
    else
        echo "       Docker already installed: $(docker --version)"
    fi

    if ! docker compose version &>/dev/null 2>&1; then
        echo "       Installing Docker Compose plugin..."
        apt-get update -qq
        apt-get install -y -qq docker-compose-plugin
    else
        echo "       Docker Compose already installed: $(docker compose version)"
    fi
'

# ---------- Step 3: bundle project ----------
echo "[3/6] Bundling project files..."
TARFILE="${PROJECT}-deploy.tar.gz"

tar --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude="db.sqlite3" \
    --exclude="db.sqlite3-journal" \
    --exclude=".git" \
    --exclude=".venv" \
    --exclude="venv" \
    --exclude="env" \
    --exclude="node_modules" \
    --exclude="${TARFILE}" \
    -czf "${TARFILE}" .

echo "       Created ${TARFILE} ($(du -h "${TARFILE}" | cut -f1))"

# ---------- Step 4: upload to VPS ----------
echo "[4/6] Uploading to VPS..."
ssh "${VPS_USER}@${VPS_IP}" "mkdir -p ${REMOTE_DIR}"
scp "${TARFILE}" "${VPS_USER}@${VPS_IP}:${REMOTE_DIR}/"
rm -f "${TARFILE}"

ssh "${VPS_USER}@${VPS_IP}" "
    set -e
    cd ${REMOTE_DIR}
    echo '       Extracting...'
    tar -xzf ${TARFILE}
    rm -f ${TARFILE}
"

# ---------- Step 5: env file ----------
echo "[5/6] Checking .env file on VPS..."
ssh "${VPS_USER}@${VPS_IP}" "
    cd ${REMOTE_DIR}
    if [ ! -f .env ]; then
        echo '       No .env found — creating from .env.example...'
        echo '       '
        echo '       ============================================='
        echo '       EDIT THESE VALUES BEFORE THE NEXT STEP:'
        echo '       ============================================='
        cp .env.example .env
        echo '       Created .env from .env.example.'
        echo ''
        echo '       REQUIRED: Set these in .env now:'
        echo '         DJANGO_SECRET_KEY    (generate: openssl rand -hex 32)'
        echo '         DB_PASSWORD          (strong Postgres password)'
        echo '         DOMAIN               (your actual domain or VPS IP)'
        echo '         DJANGO_ALLOWED_HOSTS (your domain, plus VPS IP for testing)'
    else
        echo '       .env already exists. Verify it has correct values.'
    fi

    echo ''
    echo '       Current .env content:'
    echo '       ---------------------'
    grep -E '^(DJANGO_SECRET_KEY|DJANGO_DEBUG|DJANGO_ALLOWED_HOSTS|DB_PASSWORD|DB_NAME|DB_USER|DOMAIN|SEED_DATABASE)=' .env 2>/dev/null || echo '       (not yet configured)'
"

# ---------- Step 6: build & launch ----------
echo ""
echo "[6/6] Building and launching containers..."
ssh "${VPS_USER}@${VPS_IP}" "
    set -e
    cd ${REMOTE_DIR}

    echo '       Generating secure SECRET_KEY if not set...'
    # auto-generate only if .env has the placeholder
    if grep -q 'change-me-to-a-random-50-char-string' .env 2>/dev/null; then
        NEW_KEY=\$(openssl rand -hex 32)
        sed -i \"s/change-me-to-a-random-50-char-string/\${NEW_KEY}/\" .env
        echo '       Generated new DJANGO_SECRET_KEY.'
    fi

    echo '       Building image...'
    docker compose build

    echo '       Starting services...'
    docker compose up -d

    echo '       Waiting for Django to be ready...'
    for i in \$(seq 1 30); do
        if docker compose exec -T django curl -sf http://localhost:8000/ &>/dev/null; then
            echo '       Django is ready.'
            break
        fi
        sleep 2
    done

    echo ''
    echo '       Container status:'
    docker compose ps
"

echo ""
echo "========================================="
echo "  Deploy complete!"
echo "  Site: http://${VPS_IP}"
echo "========================================="
echo ""
echo "Post-deploy checklist:"
echo "  1. Visit http://${VPS_IP} — verify the site loads"
echo "  2. SSH in and create an admin user:"
echo "     ssh ${VPS_USER}@${VPS_IP}"
echo "     cd ${REMOTE_DIR}"
echo "     docker compose exec django python manage.py createsuperuser"
echo "  3. Set up SSL with Certbot + Let's Encrypt when you have a domain"
echo "  4. View logs: docker compose logs -f"
echo "  5. Restart:   docker compose restart"
echo ""