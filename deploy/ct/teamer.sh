#!/usr/bin/env bash
# Teamer — creazione LXC su Proxmox VE (stile community-scripts, standalone)
#
# Uso dalla shell del nodo Proxmox:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/ilciko/teamer/main/deploy/ct/teamer.sh)"
#
# Variabili opzionali (override via env):
#   CTID, HOSTNAME, DISK_GB, RAM_MB, CORES, BRIDGE, NET_IP (dhcp|CIDR), GATEWAY,
#   STORAGE (rootfs), TEMPLATE_STORAGE, APP_PORT,
#   GH_REPO (predefinito ilciko/teamer, o un fork), GH_TOKEN (solo per un repo privato)
set -euo pipefail

APP="Teamer"
HOSTNAME="${HOSTNAME:-teamer}"
DISK_GB="${DISK_GB:-4}"
RAM_MB="${RAM_MB:-1024}"
CORES="${CORES:-1}"
BRIDGE="${BRIDGE:-vmbr0}"
NET_IP="${NET_IP:-dhcp}"
GATEWAY="${GATEWAY:-}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
APP_PORT="${APP_PORT:-8080}"
GH_REPO="${GH_REPO:-ilciko/teamer}"
GH_TOKEN="${GH_TOKEN:-}"

msg()  { echo -e "\e[1;34m[teamer]\e[0m $*"; }
ok()   { echo -e "\e[1;32m[ok]\e[0m $*"; }
fail() { echo -e "\e[1;31m[errore]\e[0m $*"; exit 1; }

command -v pveversion >/dev/null || fail "Questo script va eseguito sulla shell del nodo Proxmox."

# --- template Debian 13 (dell'architettura dell'host!) ---
HOST_ARCH=$(dpkg --print-architecture)   # amd64 / arm64
msg "Cerco il template Debian 13 per ${HOST_ARCH}..."
pveam update >/dev/null
TEMPLATE=$(pveam available --section system | awk '{print $2}' \
  | grep -E "^debian-13-standard.*_${HOST_ARCH}\.tar" | sort -V | tail -1)
[[ -n "$TEMPLATE" ]] || fail "Template debian-13-standard (${HOST_ARCH}) non trovato in pveam available."
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
  msg "Scarico $TEMPLATE su $TEMPLATE_STORAGE..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi
ok "Template: $TEMPLATE"

# --- creazione container ---
CTID="${CTID:-$(pvesh get /cluster/nextid)}"
NETCFG="name=eth0,bridge=${BRIDGE},ip=${NET_IP}"
[[ "$NET_IP" != "dhcp" && -n "$GATEWAY" ]] && NETCFG="${NETCFG},gw=${GATEWAY}"

msg "Creo LXC $CTID (unprivileged, ${CORES}c/${RAM_MB}MB/${DISK_GB}GB)..."
pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" --memory "$RAM_MB" --swap 512 \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --net0 "$NETCFG" \
  --unprivileged 1 --features nesting=1 \
  --onboot 1 --tags "teamer;hr" \
  --description "Teamer — gestione team (deploy automatico da ${GH_REPO})"
pct start "$CTID"
ok "Container $CTID avviato"

msg "Attendo la rete nel container..."
for _ in $(seq 1 30); do
  pct exec "$CTID" -- bash -c "ping -c1 -W1 deb.debian.org >/dev/null 2>&1" && break
  sleep 2
done

# --- install dentro il container ---
msg "Scarico ed eseguo l'install script dal repo..."
auth=()
if [[ -n "$GH_TOKEN" ]]; then auth=(-H "Authorization: Bearer ${GH_TOKEN}"); fi
INSTALL_SCRIPT=$(curl -fsSL "${auth[@]}" \
  "https://raw.githubusercontent.com/${GH_REPO}/main/deploy/install/teamer-install.sh")
[[ -n "$INSTALL_SCRIPT" ]] || fail "Install script non scaricabile (repo corretto?)."
pct exec "$CTID" -- bash -c "GH_REPO='${GH_REPO}' GH_TOKEN='${GH_TOKEN}' APP_PORT='${APP_PORT}' bash -s" <<<"$INSTALL_SCRIPT"

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
ok "${APP} installato!"
echo -e "\n  URL interno:  http://${IP}:${APP_PORT}"
echo -e "  Reverse proxy: puntare a questo indirizzo (TLS a carico del proxy)"
echo -e "  Aggiornare:    dall'app (Configurazione → Aggiornamenti) o pct exec ${CTID} -- /usr/local/bin/teamer-update\n"
