#!/usr/bin/env bash
# Teamer — creazione LXC su Proxmox VE (stile community-scripts, standalone)
#
# Uso dalla shell del nodo Proxmox:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/ilciko/teamer/main/deploy/ct/teamer.sh)"
#
# Da terminale interattivo propone un riepilogo (whiptail) con i valori rilevati sul nodo
# (storage per dischi e template, bridge, primo CTID libero): "Crea" o "Modifica" per
# sceglierli uno per uno. Senza terminale (o con NONINTERACTIVE=1) usa i valori rilevati.
#
# Variabili opzionali (fanno da valore proposto):
#   CTID, CT_HOSTNAME, DISK_GB, RAM_MB, CORES, BRIDGE, VLAN, NET_IP (dhcp|CIDR), GATEWAY,
#   BRIDGE2, VLAN2, NET_IP2, GATEWAY2 (seconda rete, eth1: BRIDGE2 vuoto = nessuna; il container
#   risponde a ognuna dal suo gateway, vedi deploy/install/teamer-multihome),
#   STORAGE (dischi del container), TEMPLATE_STORAGE, APP_PORT,
#   GH_REPO (predefinito ilciko/teamer, o un fork), GH_TOKEN (solo per un repo privato),
#   NONINTERACTIVE=1 (niente domande), DRY_RUN=1 (mostra cosa farebbe, senza creare nulla)
set -euo pipefail

APP="Teamer"
CT_HOSTNAME="${CT_HOSTNAME:-teamer}"   # non HOSTNAME: bash la imposta già al nome del nodo
DISK_GB="${DISK_GB:-4}"
RAM_MB="${RAM_MB:-1024}"
CORES="${CORES:-1}"
BRIDGE="${BRIDGE:-}"
VLAN="${VLAN:-}"
NET_IP="${NET_IP:-dhcp}"
GATEWAY="${GATEWAY:-}"
BRIDGE2="${BRIDGE2:-}"
VLAN2="${VLAN2:-}"
NET_IP2="${NET_IP2:-dhcp}"
GATEWAY2="${GATEWAY2:-}"
STORAGE="${STORAGE:-}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-}"
APP_PORT="${APP_PORT:-8080}"
GH_REPO="${GH_REPO:-ilciko/teamer}"
GH_TOKEN="${GH_TOKEN:-}"
NONINTERACTIVE="${NONINTERACTIVE:-0}"
DRY_RUN="${DRY_RUN:-0}"
TITLE="Teamer — nuovo container LXC"

msg()  { echo -e "\e[1;34m[teamer]\e[0m $*"; }
ok()   { echo -e "\e[1;32m[ok]\e[0m $*"; }
fail() { echo -e "\e[1;31m[errore]\e[0m $*"; exit 1; }

command -v pveversion >/dev/null || fail "Questo script va eseguito sulla shell del nodo Proxmox."

INTERACTIVE=0
if [[ "$NONINTERACTIVE" != "1" && -t 0 && -t 1 ]] && command -v whiptail >/dev/null; then
  INTERACTIVE=1
fi

# ---------------------------------------------------------------- rilevamento del nodo

storages_for() {   # contenuto (rootdir|vztmpl) → righe "nome tipo GB_liberi"
  pvesm status -content "$1" 2>/dev/null \
    | awk 'NR>1 && $3=="active" {printf "%s %s %.0f\n", $1, $2, $6/1024/1024}'
}

bridges() {
  ip -o link show type bridge 2>/dev/null | awk -F': ' '{print $2}' | cut -d@ -f1 | sort -V
}

pick_default() {   # $1 = preferito, resto = elenco: il preferito se c'è, altrimenti il primo
  local pref="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$pref" ]] && { echo "$x"; return; }; done
  echo "${1:-}"
}

mapfile -t ROOT_STORES < <(storages_for rootdir)
mapfile -t TMPL_STORES < <(storages_for vztmpl)
mapfile -t BRIDGES < <(bridges)
(( ${#ROOT_STORES[@]} )) || fail "Nessuno storage attivo per i dischi dei container (contenuto 'rootdir')."
(( ${#TMPL_STORES[@]} )) || fail "Nessuno storage attivo per i template (contenuto 'vztmpl')."
(( ${#BRIDGES[@]} )) || fail "Nessun bridge di rete trovato sul nodo."

root_names=(); for s in "${ROOT_STORES[@]}"; do root_names+=("${s%% *}"); done
tmpl_names=(); for s in "${TMPL_STORES[@]}"; do tmpl_names+=("${s%% *}"); done
STORAGE="${STORAGE:-$(pick_default local-lvm "${root_names[@]}")}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-$(pick_default local "${tmpl_names[@]}")}"
BRIDGE="${BRIDGE:-$(pick_default vmbr0 "${BRIDGES[@]}")}"
CTID="${CTID:-$(pvesh get /cluster/nextid)}"

# ---------------------------------------------------------------- whiptail

ask() {   # titolo testo valore → risposta (Annulla = esce)
  whiptail --title "$TITLE" --inputbox "$2" 10 64 "$3" 3>&1 1>&2 2>&3 || fail "Annullato."
}

menu_storage() {   # testo corrente righe... → nome scelto
  local text="$1" current="$2"; shift 2
  local items=() s name type free
  for s in "$@"; do
    read -r name type free <<<"$s"
    items+=("$name" "${type} · ${free} GB liberi")
  done
  whiptail --title "$TITLE" --default-item "$current" --menu "$text" 16 64 6 "${items[@]}" \
    3>&1 1>&2 2>&3 || fail "Annullato."
}

menu_bridge() {   # testo corrente [nessuna] → bridge scelto ('' = nessuna)
  local text="$1" current="$2" none="${3:-}" items=() b
  [[ -n "$none" ]] && items+=("nessuna" "una sola rete")
  for b in "${BRIDGES[@]}"; do items+=("$b" "bridge"); done
  b=$(whiptail --title "$TITLE" --default-item "${current:-nessuna}" --menu "$text" 16 64 6 \
    "${items[@]}" 3>&1 1>&2 2>&3) || fail "Annullato."
  [[ "$b" == "nessuna" ]] && b=""
  echo "$b"
}

valid_ip() { [[ "$1" == "dhcp" || "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; }

valid_ctid() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 100 )) && pvesh get /cluster/nextid --vmid "$1" &>/dev/null
}

edit_settings() {
  local v
  while :; do
    v=$(ask "CTID" "ID del container (libero, da 100 in su)" "$CTID")
    if valid_ctid "$v"; then CTID="$v"; break; fi
    whiptail --title "$TITLE" --msgbox "Il CTID ${v} non è valido o è già in uso." 8 50
  done
  CT_HOSTNAME=$(ask "Hostname" "Nome host del container" "$CT_HOSTNAME")
  CORES=$(ask "CPU" "Core CPU" "$CORES")
  RAM_MB=$(ask "RAM" "Memoria in MB" "$RAM_MB")
  DISK_GB=$(ask "Disco" "Disco in GB" "$DISK_GB")
  STORAGE=$(menu_storage "Storage per il disco del container" "$STORAGE" "${ROOT_STORES[@]}")
  TEMPLATE_STORAGE=$(menu_storage "Storage per il template Debian 13" "$TEMPLATE_STORAGE" "${TMPL_STORES[@]}")
  BRIDGE=$(menu_bridge "Bridge di rete del container (eth0)" "$BRIDGE")
  VLAN=$(ask "VLAN" "Tag VLAN (vuoto = nessuna)" "$VLAN")
  while :; do
    NET_IP=$(ask "IP" "Indirizzo IPv4: 'dhcp' oppure statico in CIDR (es. 192.0.2.50/24)" "$NET_IP")
    valid_ip "$NET_IP" && break
    whiptail --title "$TITLE" --msgbox "Formato non valido: usa 'dhcp' o un indirizzo CIDR." 8 50
  done
  if [[ "$NET_IP" != "dhcp" ]]; then
    GATEWAY=$(ask "Gateway" "Gateway IPv4" "$GATEWAY")
  else
    GATEWAY=""
  fi
  BRIDGE2=$(menu_bridge "Seconda rete (eth1), se il container deve rispondere anche da un'altra rete" "$BRIDGE2" nessuna)
  if [[ -n "$BRIDGE2" ]]; then
    VLAN2=$(ask "VLAN" "Tag VLAN della seconda rete (vuoto = nessuna)" "$VLAN2")
    while :; do
      NET_IP2=$(ask "IP" "Indirizzo IPv4 sulla seconda rete: 'dhcp' oppure CIDR" "$NET_IP2")
      valid_ip "$NET_IP2" && break
      whiptail --title "$TITLE" --msgbox "Formato non valido: usa 'dhcp' o un indirizzo CIDR." 8 50
    done
    if [[ "$NET_IP2" != "dhcp" ]]; then
      GATEWAY2=$(ask "Gateway" "Gateway della seconda rete (le risposte verso chi arriva da lì escono da qui)" "$GATEWAY2")
    else
      GATEWAY2=""
    fi
  fi
  APP_PORT=$(ask "Porta" "Porta HTTP di Teamer nel container" "$APP_PORT")
}

summary() {
  cat <<TXT
CTID           ${CTID}
Hostname       ${CT_HOSTNAME}
Risorse        ${CORES} CPU · ${RAM_MB} MB RAM · ${DISK_GB} GB disco
Storage disco  ${STORAGE}
Template su    ${TEMPLATE_STORAGE}
Rete           ${BRIDGE}${VLAN:+ (VLAN ${VLAN})} · ${NET_IP}${GATEWAY:+ via ${GATEWAY}}
Seconda rete   ${BRIDGE2:-nessuna}${BRIDGE2:+${VLAN2:+ (VLAN ${VLAN2})} · ${NET_IP2}${GATEWAY2:+ via ${GATEWAY2}}}
Porta          ${APP_PORT}
Codice da      github.com/${GH_REPO}
TXT
}

if (( INTERACTIVE )); then
  while ! whiptail --title "$TITLE" --yes-button "Crea" --no-button "Modifica" \
      --yesno "Il container verrà creato così:\n\n$(summary)\n" 19 70; do
    edit_settings
  done
else
  valid_ctid "$CTID" || fail "CTID ${CTID} non valido o già in uso."
  msg "Impostazioni:"; summary
fi

[[ "$CORES" =~ ^[0-9]+$ && "$RAM_MB" =~ ^[0-9]+$ && "$DISK_GB" =~ ^[0-9]+$ && "$APP_PORT" =~ ^[0-9]+$ ]] \
  || fail "CPU, RAM, disco e porta devono essere numeri interi."
[[ -z "$VLAN" || "$VLAN" =~ ^[0-9]+$ ]] || fail "VLAN deve essere un numero."
[[ -z "$VLAN2" || "$VLAN2" =~ ^[0-9]+$ ]] || fail "VLAN2 deve essere un numero."
valid_ip "$NET_IP" || fail "NET_IP: usa 'dhcp' o un indirizzo CIDR."
[[ -z "$BRIDGE2" ]] || valid_ip "$NET_IP2" || fail "NET_IP2: usa 'dhcp' o un indirizzo CIDR."
[[ -z "$BRIDGE2" || "$BRIDGE2" != "$BRIDGE" || "$VLAN2" != "$VLAN" ]] || fail "La seconda rete coincide con la prima."

# ---------------------------------------------------------------- template Debian 13

HOST_ARCH=$(dpkg --print-architecture)   # amd64 / arm64: il template deve essere dell'architettura dell'host
NETCFG="name=eth0,bridge=${BRIDGE},ip=${NET_IP}"
[[ -n "$VLAN" ]] && NETCFG="${NETCFG},tag=${VLAN}"
[[ "$NET_IP" != "dhcp" && -n "$GATEWAY" ]] && NETCFG="${NETCFG},gw=${GATEWAY}"
# seconda rete: il gateway NON va nella config del container (due default in interfaces e ifup
# fallisce): lo mette teamer-multihome in una tabella per sorgente, da DHCP o da post-up
NET1_ARGS=()
if [[ -n "$BRIDGE2" ]]; then
  NETCFG2="name=eth1,bridge=${BRIDGE2},ip=${NET_IP2}"
  [[ -n "$VLAN2" ]] && NETCFG2="${NETCFG2},tag=${VLAN2}"
  NET1_ARGS=(--net1 "$NETCFG2")
fi

if [[ "$DRY_RUN" == "1" ]]; then
  msg "DRY_RUN: niente viene creato. Comando previsto:"
  echo "pct create ${CTID} ${TEMPLATE_STORAGE}:vztmpl/debian-13-standard_<ultima>_${HOST_ARCH}.tar.zst" \
       "--hostname ${CT_HOSTNAME} --cores ${CORES} --memory ${RAM_MB} --rootfs ${STORAGE}:${DISK_GB}" \
       "--net0 ${NETCFG}${NET1_ARGS[*]:+ ${NET1_ARGS[*]}} --unprivileged 1 --features nesting=1 --onboot 1"
  exit 0
fi

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

# ---------------------------------------------------------------- creazione container

msg "Creo LXC $CTID (unprivileged, ${CORES}c/${RAM_MB}MB/${DISK_GB}GB)..."
pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$CT_HOSTNAME" \
  --cores "$CORES" --memory "$RAM_MB" --swap 512 \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --net0 "$NETCFG" "${NET1_ARGS[@]}" \
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

# ---------------------------------------------------------------- install dentro il container

msg "Scarico ed eseguo l'install script dal repo..."
auth=()
if [[ -n "$GH_TOKEN" ]]; then auth=(-H "Authorization: Bearer ${GH_TOKEN}"); fi
INSTALL_SCRIPT=$(curl -fsSL "${auth[@]}" \
  "https://raw.githubusercontent.com/${GH_REPO}/main/deploy/install/teamer-install.sh")
[[ -n "$INSTALL_SCRIPT" ]] || fail "Install script non scaricabile (repo corretto?)."
pct exec "$CTID" -- bash -c "GH_REPO='${GH_REPO}' GH_TOKEN='${GH_TOKEN}' APP_PORT='${APP_PORT}' bash -s" <<<"$INSTALL_SCRIPT"

if [[ -n "$BRIDGE2" ]]; then
  msg "Seconda rete: rotte per sorgente su eth1..."
  if [[ "$NET_IP2" != "dhcp" && -n "$GATEWAY2" ]]; then
    # Proxmox rigenera la sezione di eth1 a ogni avvio ma conserva queste righe
    pct exec "$CTID" -- bash -c "awk -v up='post-up /usr/local/sbin/teamer-multihome eth1 up ${NET_IP2%/*} ${GATEWAY2}' \
        -v down='pre-down /usr/local/sbin/teamer-multihome eth1 down' \
        '{print} /^iface eth1 inet static/ {print \"\t\" up; print \"\t\" down}' /etc/network/interfaces \
        > /etc/network/interfaces.new && mv /etc/network/interfaces.new /etc/network/interfaces"
  fi
  pct exec "$CTID" -- bash -c "ifdown eth1 >/dev/null 2>&1; ifup eth1"   # DHCP: l'hook dhclient applica la rotta al lease
fi

IPS=$(pct exec "$CTID" -- hostname -I)
ok "${APP} installato!"
for ip in $IPS; do echo -e "\n  URL interno:  http://${ip}:${APP_PORT}"; done
echo -e "  Reverse proxy: puntare a questo indirizzo (TLS a carico del proxy)"
echo -e "  Primo accesso: site admin con la password provvisoria stampata sopra dall'installer"
echo -e "  Chiave del DB: /etc/teamer/db.key nel container — salvane una copia fuori (senza, i dati sono persi)"
echo -e "  Utenti:        dall'app (Amministrazione → Utenti) o pct exec ${CTID} -- /usr/local/bin/teamer-admin"
echo -e "  Aggiornare:    dall'app (Amministrazione → Aggiornamenti) o pct exec ${CTID} -- /usr/local/bin/teamer-update\n"
