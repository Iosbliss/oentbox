# ==========================================================
#  OentBox VPS Deploy Script (PowerShell edition)
#  One-command Docker deployment to a Linux VPS from Windows
#  Usage: .\deploy.ps1                        (uses defaults)
#         .\deploy.ps1 -VpsIp 1.2.3.4
#         .\deploy.ps1 -VpsIp 1.2.3.4 -VpsUser root
# ==========================================================

param(
    [string]$VpsIp   = "199.246.88.46",
    [string]$VpsUser = "root",
    [string]$RemoteDir = "/opt/oentbox"
)

$ErrorActionPreference = "Stop"
$Project = "oentbox"
$TarFile = "$Project-deploy.tar.gz"

function Write-Step($n, $total, $msg) {
    Write-Host "`n[$n/$total] $msg" -ForegroundColor Cyan
}
function Write-Sub($msg) {
    Write-Host "       $msg" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Yellow
Write-Host "  OentBox Docker Deploy" -ForegroundColor Yellow
Write-Host "  Target: $VpsUser@$VpsIp`:$RemoteDir" -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "You will be asked for the VPS password multiple times." -ForegroundColor Yellow
Write-Host "Each SSH/SCP call opens a new session." -ForegroundColor Yellow
Write-Host "(To avoid repeated prompts, set up SSH keys afterward.)" -ForegroundColor DarkGray
Write-Host ""

# ---------- Step 1: check SSH ----------
Write-Step 1 6 "Checking SSH connection (enter VPS password when prompted)..."
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$VpsUser@$VpsIp" "echo SSH-OK"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Cannot SSH to $VpsUser@$VpsIp" -ForegroundColor Red
    exit 1
}

# ---------- Step 2: install Docker ----------
Write-Step 2 6 "Installing Docker & Docker Compose on VPS (enter password when prompted)..."
$dockerScript = @'
set -e
if ! command -v docker >/dev/null 2>&1; then
    echo "       Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "       Docker already installed: $(docker --version)"
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "       Installing Docker Compose plugin..."
    apt-get update -qq
    apt-get install -y -qq docker-compose-plugin
else
    echo "       Docker Compose already installed: $(docker compose version)"
fi
'@
ssh "$VpsUser@$VpsIp" $dockerScript

# ---------- Step 3: bundle project ----------
Write-Step 3 6 "Bundling project files..."
$excludes = @(
    "__pycache__", "*.pyc", "*.pyo", "db.sqlite3", "db.sqlite3-journal",
    ".git", ".venv", "venv", "env", "node_modules",
    "*.tar.gz", "*.log", ".env"
)
# Use Python to build the tarball (tar.exe on Windows is limited)
$excludeArgs = ($excludes | ForEach-Object { "--exclude=`"$_`"" }) -join " "
$pyScript = @"
import tarfile, os, fnmatch
excludes = $($excludes | ConvertTo-Json -Compress)
out = "$TarFile"
def excluded(name):
    base = os.path.basename(name)
    for pat in excludes:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(base, pat):
            return True
    return False
count = 0
with tarfile.open(out, "w:gz") as tar:
    for root, dirs, files in os.walk("."):
        if ".git" in root.split(os.sep): continue
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, ".")
            if excluded(rel): continue
            if rel == out: continue
            tar.add(fp, arcname=rel)
            count += 1
print(f"       Packed {count} files -> {out}")
"@
python -c $pyScript
if ($LASTEXITCODE -ne 0) {
    # fallback: try tar.exe (Windows 10+ has bsdtar)
    Write-Sub "Trying tar.exe as fallback..."
    tar $excludeArgs -czf $TarFile .
}
$size = [math]::Round((Get-Item $TarFile).Length / 1MB, 2)
Write-Sub "Created $TarFile ($size MB)"

# ---------- Step 4: upload to VPS ----------
Write-Step 4 6 "Uploading to VPS (enter password when prompted)..."
ssh "$VpsUser@$VpsIp" "mkdir -p $RemoteDir"
scp $TarFile "${VpsUser}@${VpsIp}:$RemoteDir/"
Remove-Item -Force $TarFile -ErrorAction SilentlyContinue

ssh "$VpsUser@$VpsIp" "set -e; cd $RemoteDir; echo '       Extracting...'; tar -xzf $TarFile; rm -f $TarFile"

# ---------- Step 5: env file ----------
Write-Step 5 6 "Configuring .env on VPS (enter password when prompted)..."
$envScript = @"
cd $RemoteDir
if [ ! -f .env ]; then
    echo '       No .env found - creating from .env.example...'
    cp .env.example .env
    echo '       Generated .env from .env.example.'
else
    echo '       .env already exists - verifying.'
fi

# Auto-generate SECRET_KEY if it still has the placeholder
if grep -q 'change-me-to-a-random-50-char-string' .env 2>/dev/null; then
    NEW_KEY=\`$(openssl rand -hex 32)
    sed -i "s/change-me-to-a-random-50-char-string/\$NEW_KEY/" .env
    echo '       Generated new DJANGO_SECRET_KEY.'
fi

# Auto-generate DB_PASSWORD if placeholder
if grep -q 'change-me-strong-db-password' .env 2>/dev/null; then
    NEW_PW=\`$(openssl rand -hex 16)
    sed -i "s/change-me-strong-db-password/\$NEW_PW/" .env
    echo '       Generated new DB_PASSWORD.'
fi

# Set ALLOWED_HOSTS and DOMAIN to the VPS IP if still placeholders
if grep -q 'your-domain.com' .env 2>/dev/null; then
    sed -i 's/your-domain.com,www.your-domain.com/$VpsIp/' .env
    sed -i "s/^DOMAIN=.*/DOMAIN=$VpsIp/" .env
    echo '       Set ALLOWED_HOSTS and DOMAIN to VPS IP ($VpsIp).'
fi

echo ''
echo '       .env configured. Summary:'
echo '       ---------------------------'
grep -E '^(DJANGO_SECRET_KEY|DJANGO_DEBUG|DJANGO_ALLOWED_HOSTS|DB_PASSWORD|DB_NAME|DB_USER|DOMAIN|SEED_DATABASE)=' .env | sed 's/DJANGO_SECRET_KEY=.*/DJANGO_SECRET_KEY=***hidden***/' | sed 's/DB_PASSWORD=.*/DB_PASSWORD=***hidden***/'
"@
ssh "$VpsUser@$VpsIp" $envScript

# ---------- Step 6: build & launch ----------
Write-Step 6 6 "Building and launching containers (enter password when prompted)..."
$buildScript = @"
set -e
cd $RemoteDir

echo '       Building Docker image...'
docker compose build

echo '       Starting services...'
docker compose up -d

echo '       Waiting for Postgres...'
for i in `$(seq 1 15); do
    if docker compose exec -T db pg_isready -U oentbox >/dev/null 2>&1; then
        echo '       Postgres is ready.'
        break
    fi
    sleep 2
done

echo '       Waiting for Django...'
for i in `$(seq 1 30); do
    if docker compose exec -T django curl -sf http://localhost:8000/ >/dev/null 2>&1; then
        echo '       Django is ready.'
        break
    fi
    sleep 2
done

echo ''
echo '       Container status:'
docker compose ps
"@
ssh "$VpsUser@$VpsIp" $buildScript

# ---------- Done ----------
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Deploy complete!" -ForegroundColor Green
Write-Host "  Site: http://$VpsIp" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Post-deploy checklist:" -ForegroundColor Yellow
Write-Host "  1. Open http://$VpsIp in your browser - verify the site loads"
Write-Host "  2. Create an admin user:"
Write-Host "     ssh $VpsUser@$VpsIp" -ForegroundColor White
Write-Host "     cd $RemoteDir" -ForegroundColor White
Write-Host "     docker compose exec django python manage.py createsuperuser" -ForegroundColor White
Write-Host "  3. View logs: docker compose logs -f"
Write-Host "  4. Restart:   docker compose restart"
Write-Host ""
Write-Host "Tip: To avoid repeated password prompts next time, set up SSH keys:" -ForegroundColor DarkGray
Write-Host "  ssh-keygen -t ed25519" -ForegroundColor DarkGray
Write-Host "  type `$env:USERPROFILE\.ssh\id_ed25519.pub | ssh $VpsUser@$VpsIp 'cat >> ~/.ssh/authorized_keys'" -ForegroundColor DarkGray
Write-Host ""
