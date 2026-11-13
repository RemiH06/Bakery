#!/usr/bin/env bash
# Instala o actualiza el agente de máquina de Bakery en una Pi (o cualquier Debian con systemd y polkit).
# Uso, en la máquina: sudo ./agente-setup.sh [ruta/a/agente.py]
#   Por defecto toma agente.py junto a este script o, en un clon del repo, bakers/src/bakers/agente.py.
# La primera vez deja una plantilla en /etc/bakery-agente.toml y se detiene: llénala y vuelve a correrlo.
# Cada vez que cambien `acciones` en la configuración, volver a correrlo (rehace la regla de polkit).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Córrelo con sudo" >&2; exit 1; }
aqui="$(cd "$(dirname "$0")" && pwd)"
origen="${1:-}"
[[ -n $origen ]] || for c in "$aqui/agente.py" "$aqui/../../bakers/src/bakers/agente.py"; do [[ -f $c ]] && origen="$c" && break; done
[[ -f ${origen:-} ]] || { echo "No encuentro agente.py; pásalo como argumento" >&2; exit 1; }
config=/etc/bakery-agente.toml
puerto=8094  # registrado en 48.SkillShot/PORTS.md

# Usuario propio, sin shell ni home: si el agente tuviera un error, no hereda los permisos de nadie.
# systemd-journal: leer el log de las unidades sin ser root.
id bakery-agente &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin bakery-agente
usermod -aG systemd-journal bakery-agente

# Copia de root: el usuario de siempre (con sudo) no puede cambiar el código que corre el servicio
install -d -o root -g root -m 755 /opt/bakery-agente
install -o root -g root -m 644 "$origen" /opt/bakery-agente/agente.py

if [[ ! -f $config ]]; then
  cat > "$config" <<EOF
# Agente de máquina de Bakery (ver la cabecera de agente.py). Sin \`usuarios\` no arranca.
nombre = "$(hostname)"
usuarios = []      # logins del tailnet que pueden entrar, p. ej. ["alguien@github"]
origenes = []      # el panel, p. ej. ["https://<pixilate>.<tailnet>.ts.net:8093"]
servicios = []     # unidades de systemd que se muestran, sin .service
acciones = []      # las que se pueden iniciar, detener y reiniciar (también en servicios)

[ordenes]
# despertar-pixilate = ["/usr/local/bin/wake-pixilate"]
EOF
  chown root:bakery-agente "$config"; chmod 640 "$config"
  echo "Plantilla en $config: llénala y vuelve a correr este script."
  exit 0
fi
chown root:bakery-agente "$config"; chmod 640 "$config"

# La configuración la valida el mismo agente (falla aquí y no al arrancar el servicio)
acciones="$(python3 -I - "$config" <<'EOF'
import sys
sys.path.insert(0, "/opt/bakery-agente")
import agente
cfg = agente.cargar(__import__("pathlib").Path(sys.argv[1]))
if not cfg.usuarios:
    sys.exit("Falta `usuarios` en la configuración")
print(" ".join(f'"{a}.service"' for a in cfg.acciones))
EOF
)"

# polkit: el agente puede iniciar, detener y reiniciar solo las unidades de `acciones`, sin sudo (el servicio
# corre con NoNewPrivileges, que de todos modos impediría sudo)
cat > /etc/polkit-1/rules.d/50-bakery-agente.rules <<EOF
// Generado por agente-setup.sh de Bakery: no editar a mano, cambiar \`acciones\` en $config y volver a correrlo.
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.systemd1.manage-units" && subject.user == "bakery-agente") {
    var unidades = [${acciones// /, }];
    var verbos = ["start", "stop", "restart"];
    if (unidades.indexOf(action.lookup("unit")) >= 0 && verbos.indexOf(action.lookup("verb")) >= 0) {
      return polkit.Result.YES;
    }
    return polkit.Result.NO;
  }
});
EOF
chmod 644 /etc/polkit-1/rules.d/50-bakery-agente.rules

cat > /etc/systemd/system/bakery-agente.service <<EOF
[Unit]
Description=Agente de máquina de Bakery (panel, solo tailnet)
After=network-online.target
Wants=network-online.target

[Service]
User=bakery-agente
Group=bakery-agente
ExecStart=/usr/bin/python3 -I /opt/bakery-agente/agente.py --puerto $puerto
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=yes
LockPersonality=yes
MemoryMax=128M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bakery-agente.service >/dev/null
systemctl restart bakery-agente.service
# Solo al tailnet; tailscale serve agrega Tailscale-User-Login, que el agente exige
tailscale serve --bg --https=$puerto http://127.0.0.1:$puerto >/dev/null
sleep 1
systemctl --no-pager --lines=3 status bakery-agente.service | head -5
codigo=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$puerto/api/maquina || true)
echo "Sin identidad del tailnet responde $codigo (debe ser 403)."
echo "Apagar: sudo tailscale serve --https=$puerto off && sudo systemctl disable --now bakery-agente"
