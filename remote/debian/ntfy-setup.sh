#!/usr/bin/env bash
# Instala o actualiza ntfy (avisos al teléfono) en una Pi de Bakery, solo para la tailnet.
# Uso, en la máquina: sudo ./ntfy-setup.sh TEMA [TEMA...]
#   Cada TEMA es un proyecto que publica avisos (p. ej. `tabularium`): recibe un usuario de ntfy con el
#   mismo nombre que solo puede escribir en su tema, y un token en ~/.config/ntfy/TEMA.env del usuario
#   que corre sudo (modo 600), con NTFY_URL y NTFY_TOKEN.
#   El usuario `remi` puede leer todos los temas; su contraseña queda en /etc/ntfy/remi.txt (solo root):
#   con ella se entra desde la app de ntfy del teléfono, que necesita Tailscale.
# Se puede volver a correr: no cambia contraseñas ni tokens que ya existen.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Córrelo con sudo" >&2; exit 1; }
(( $# )) || { echo "Uso: sudo $0 TEMA [TEMA...]" >&2; exit 1; }
puerto=8095  # registrado en 48.SkillShot/PORTS.md
huella=55BA774A6F5EE67431E4B6B7CFDB962D4F1EC4AF  # la que publica docs.ntfy.sh/install
dueno="${SUDO_USER:?córrelo con sudo desde tu usuario}"

# Repositorio oficial, con la llave verificada antes de confiar en ella
if [[ ! -f /etc/apt/sources.list.d/ntfy.list ]]; then
  llave=$(mktemp)
  curl -fsSL -o "$llave" https://archive.ntfy.sh/apt/keyring.gpg
  gpg --show-keys --with-colons "$llave" | grep -q "^fpr:::::::::$huella:" \
    || { echo "La llave de archive.ntfy.sh no tiene la huella esperada; no se instala" >&2; exit 1; }
  install -d -m 755 /etc/apt/keyrings
  install -m 644 "$llave" /etc/apt/keyrings/ntfy.gpg
  rm -f "$llave"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" \
    > /etc/apt/sources.list.d/ntfy.list
fi
apt-get update -qq
apt-get install -y -qq ntfy >/dev/null

dominio=$(tailscale status --json | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
install -d -o ntfy -g ntfy -m 750 /var/cache/ntfy /var/lib/ntfy
cat > /etc/ntfy/server.yml <<EOF
# Generado por ntfy-setup.sh de Bakery: no editar a mano.
base-url: "https://$dominio:$puerto"
listen-http: "127.0.0.1:$puerto"
behind-proxy: true
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "72h"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
enable-signup: false
enable-login: true
EOF
chmod 644 /etc/ntfy/server.yml

# Tope de memoria (se aplica con cgroup_enable=memory en /boot/firmware/cmdline.txt)
install -d /etc/systemd/system/ntfy.service.d
cat > /etc/systemd/system/ntfy.service.d/bakery.conf <<EOF
[Service]
MemoryMax=128M
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/cache/ntfy /var/lib/ntfy
ProtectHome=yes
PrivateTmp=yes
EOF
systemctl daemon-reload
systemctl enable ntfy.service >/dev/null
systemctl restart ntfy.service
sleep 1

existe() { ntfy user list 2>&1 | grep -q "^user $1 "; }
if ! existe remi; then
  clave=$(python3 -I -c 'import secrets; print(secrets.token_urlsafe(18))')
  NTFY_PASSWORD="$clave" ntfy user add remi >/dev/null
  install -m 600 /dev/null /etc/ntfy/remi.txt
  printf '%s\n' "$clave" > /etc/ntfy/remi.txt
fi
ntfy access remi '*' read-only >/dev/null

for tema in "$@"; do
  [[ $tema =~ ^[a-z0-9_-]+$ ]] || { echo "Tema no válido: $tema" >&2; exit 1; }
  if ! existe "$tema"; then
    NTFY_PASSWORD="$(python3 -I -c 'import secrets; print(secrets.token_urlsafe(24))')" ntfy user add "$tema" >/dev/null
  fi
  ntfy access "$tema" "$tema" write-only >/dev/null
  archivo="$(getent passwd "$dueno" | cut -d: -f6)/.config/ntfy/$tema.env"
  if [[ ! -s $archivo ]]; then
    token=$(ntfy token add --label="$(hostname)" "$tema" 2>&1 | grep -o 'tk_[A-Za-z0-9]*' | head -1)
    [[ -n $token ]] || { echo "No se pudo crear el token de $tema" >&2; exit 1; }
    install -d -o "$dueno" -g "$dueno" -m 700 "$(dirname "$archivo")"
    install -o "$dueno" -g "$dueno" -m 600 /dev/null "$archivo"
    printf 'NTFY_URL=http://127.0.0.1:%s/%s\nNTFY_TOKEN=%s\n' "$puerto" "$tema" "$token" > "$archivo"
  fi
  echo "Tema $tema: token en $archivo"
done

# Solo al tailnet
tailscale serve --bg --https=$puerto http://127.0.0.1:$puerto >/dev/null
systemctl --no-pager --lines=3 status ntfy.service | head -4
codigo=$(curl -s -o /dev/null -w '%{http_code}' -d prueba http://127.0.0.1:$puerto/"$1" || true)
echo "Publicar sin token responde $codigo (debe ser 403)."
echo "Teléfono: app ntfy, servidor https://$dominio:$puerto, usuario remi, contraseña en /etc/ntfy/remi.txt; suscribirse a: $*"
echo "Apagar: sudo tailscale serve --https=$puerto off && sudo systemctl disable --now ntfy"
