#!/usr/bin/env bash
# Teamer — installazione dentro il container LXC (Debian 13).
# Eseguito da deploy/ct/teamer.sh. Variabili: GH_REPO (predefinito ilciko/teamer),
# GH_TOKEN (solo per un repo privato), APP_PORT.
set -euo pipefail

GH_REPO="${GH_REPO:-ilciko/teamer}"
GH_TOKEN="${GH_TOKEN:-}"
APP_PORT="${APP_PORT:-8080}"
APP_DIR="/opt/teamer"

msg() { echo -e "\e[1;34m[install]\e[0m $*"; }

export LC_ALL=C.UTF-8 LANG=C.UTF-8
# la shell di pct exec/enter (lxc-attach) può non avere /usr/local/bin nel PATH
export PATH="/usr/local/sbin:/usr/local/bin:$PATH"

msg "Aggiorno il sistema e installo le dipendenze..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq upgrade
apt-get -y -qq install curl ca-certificates tar
# su architetture senza wheel precompilata (es. arm64) sqlcipher3 si compila da sorgente
if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
  apt-get -y -qq install build-essential libsqlcipher-dev pkg-config
fi

msg "Installo uv (gestore Python)..."
UV_ARCH=$(uname -m)   # x86_64 / aarch64
curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz" \
  | tar -xzf - -C /usr/local/bin --strip-components=1
[[ -x /usr/local/bin/uv ]] || { echo "uv non installato correttamente"; exit 1; }
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
mkdir -p /opt/uv/python

msg "Creo utente e directory..."
id teamer &>/dev/null || useradd -r -d "$APP_DIR" -s /usr/sbin/nologin teamer
mkdir -p "$APP_DIR/data/update" "$APP_DIR/data/backups"

msg "Salvo la configurazione di deploy (root-only)..."
{
  echo "GH_REPO=${GH_REPO}"
  if [[ -n "$GH_TOKEN" ]]; then echo "GH_TOKEN=${GH_TOKEN}"; fi
} > "$APP_DIR/.deploy.env"
chmod 600 "$APP_DIR/.deploy.env"

msg "Configurazione applicativa..."
if [[ ! -f "$APP_DIR/.env" ]]; then
  cat > "$APP_DIR/.env" <<EOF
TEAMER_DB_PATH=${APP_DIR}/data/teamer.db
TEAMER_DB_KEY_FILE=/etc/teamer/db.key
TEAMER_HOST=0.0.0.0
TEAMER_PORT=${APP_PORT}
TEAMER_SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
TEAMER_HEARTBEAT_SECONDS=20
TEAMER_LOCK_GRACE_SECONDS=90
EOF
  chmod 640 "$APP_DIR/.env"
fi

msg "Installo l'updater..."
UPDATER_URL="https://raw.githubusercontent.com/${GH_REPO}/main/deploy/install/teamer-update"
auth=()
if [[ -n "$GH_TOKEN" ]]; then auth=(-H "Authorization: Bearer ${GH_TOKEN}"); fi
curl -fsSL "${auth[@]}" "$UPDATER_URL" -o /usr/local/bin/teamer-update
chmod 755 /usr/local/bin/teamer-update

msg "Scarico e installo l'ultima release (installa anche l'updater richiamabile dall'app)..."
/usr/local/bin/teamer-update --no-restart

msg "Servizio systemd..."
cat > /etc/systemd/system/teamer.service <<EOF
[Unit]
Description=Teamer - gestione team
After=network.target

[Service]
Type=simple
User=teamer
Group=teamer
WorkingDirectory=${APP_DIR}/src
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/src/.venv/bin/uvicorn app.main:app --host \${TEAMER_HOST} --port \${TEAMER_PORT}
Restart=on-failure
RestartSec=3
# hardening di base
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${APP_DIR}/data
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
chown -R teamer:teamer "$APP_DIR"
chown root:root "$APP_DIR/.deploy.env" && chmod 600 "$APP_DIR/.deploy.env"   # l'app non lo legge
msg "Chiave di sistema del database e primo site admin..."
ADMIN_OUT=$(/usr/local/bin/teamer-admin init)   # riportato in fondo, dove si vede

systemctl daemon-reload
systemctl enable -q --now teamer

msg "Pulizia..."
apt-get -y -qq autoremove
apt-get -y -qq clean

echo -e "\e[1;32m[ok]\e[0m Teamer attivo sulla porta ${APP_PORT}."
echo "$ADMIN_OUT"
echo "Accedi con il site admin e crea gli utenti da Amministrazione."
echo "Salva una copia di /etc/teamer/db.key fuori dal container: senza chiave i dati sono persi."
