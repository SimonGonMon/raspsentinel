#!/usr/bin/env bash
set -euo pipefail

APP_USER="raspsentinel"
APP_DIR="/opt/raspsentinel"
DATA_DIR="/var/lib/raspsentinel"
CONF_DIR="/etc/raspsentinel"
SERVICE_UNIT="/etc/systemd/system/raspsentinel.service"
REPO_URL="${REPO_URL:-https://github.com/SimonGonMon/raspsentinel.git}"
SRC_ROOT=""
TMP_SRC_DIR=""

log() { printf '[raspsentinel] %s\n' "$*" >&2; }

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Este instalador necesita privilegios de root. Ejecuta con sudo." >&2
    exit 1
  fi
}

ensure_tools() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Se requiere apt-get para instalar dependencias del sistema." >&2
    exit 1
  fi
  log "Instalando dependencias del sistema..."
  apt-get update
  apt-get install -y git python3 python3-venv python3-pip arp-scan rsync
}

prepare_source_dir() {
  local repo_guard="raspsentinel/__init__.py"
  if [[ -f "requirements.txt" && -f "$repo_guard" ]]; then
    SRC_ROOT="$(pwd)"
    TMP_SRC_DIR=""
  else
    local tmpdir
    tmpdir="$(mktemp -d)"
    log "Clonando repositorio ${REPO_URL}..."
    git clone --depth=1 "$REPO_URL" "$tmpdir/src"
    SRC_ROOT="$tmpdir/src"
    TMP_SRC_DIR="$tmpdir"
  fi
}

sync_code() {
  local src_root="$1"
  log "Copiando archivos de la aplicación..."
  # Completely remove the old directory to avoid any cache or git issues
  if [[ -d "$APP_DIR" ]]; then
    rm -rf "$APP_DIR"
  fi
  mkdir -p "$APP_DIR"
  rsync -a --delete --exclude ".git" "$src_root/" "$APP_DIR/"
  install -Dm644 "$APP_DIR/raspsentinel.service" "$SERVICE_UNIT"
}

create_user_and_paths() {
  log "Creando usuario y directorios..."
  id -u "$APP_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin "$APP_USER"
  mkdir -p "$DATA_DIR" "$CONF_DIR"
  chown -R "$APP_USER":"$APP_USER" "$DATA_DIR"
}

install_python_deps() {
  log "Configurando entorno virtual..."
  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install --upgrade pip
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
  link_package_path
}

ensure_config() {
  if [[ ! -f "$CONF_DIR/config.yaml" ]]; then
    log "Generando configuración inicial..."
    cp "$APP_DIR/config.example.yaml" "$CONF_DIR/config.yaml"
    chown "$APP_USER":"$APP_USER" "$CONF_DIR/config.yaml"
    chmod 640 "$CONF_DIR/config.yaml"
  fi
}

finalize_permissions() {
  chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
  chmod 750 "$APP_DIR"
  chown -R "$APP_USER":"$APP_USER" "$CONF_DIR" "$DATA_DIR"
}

deploy_cli_wrapper() {
  log "Instalando comando raspsentinel..."
  cat >/usr/local/bin/raspsentinel <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/opt/raspsentinel:${PYTHONPATH:-}"
export PYTHONDONTWRITEBYTECODE=1
exec /opt/raspsentinel/venv/bin/python -B -m raspsentinel.cli "$@"
EOF
  chmod +x /usr/local/bin/raspsentinel
}

enable_service() {
  log "Habilitando servicio systemd..."
  systemctl daemon-reload
  systemctl enable raspsentinel.service >/dev/null 2>&1 || true
}

cleanup_tmp() {
  if [[ -n "$TMP_SRC_DIR" && -d "$TMP_SRC_DIR" ]]; then
    rm -rf "$TMP_SRC_DIR"
  fi
}

link_package_path() {
  local site_packages
  site_packages="$("$APP_DIR/venv/bin/python" - <<'PY'
import sysconfig
print(sysconfig.get_paths()["purelib"])
PY
)"
  if [[ -z "$site_packages" || ! -d "$site_packages" ]]; then
    return
  fi
  ln -sfn "$APP_DIR/raspsentinel" "$site_packages/raspsentinel"
  cat >"$site_packages/raspsentinel-local.pth" <<EOF
/opt/raspsentinel
EOF
}

main() {
  require_root
  ensure_tools
  prepare_source_dir
  sync_code "$SRC_ROOT"
  create_user_and_paths
  install_python_deps
  ensure_config
  finalize_permissions
  deploy_cli_wrapper
  enable_service
  cleanup_tmp
  log "Instalación completa. Ejecuta 'sudo raspsentinel setup' para terminar la configuración."
}

main "$@"
