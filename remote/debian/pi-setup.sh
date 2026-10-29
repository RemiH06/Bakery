#!/usr/bin/env bash
# Mete una Raspberry al tailnet y le deja el comando wake-pixilate.
# Uso (en la Pi): remote/debian/pi-setup.sh AA:BB:CC:DD:EE:FF   (la MAC que imprime pixilate-setup.ps1)
set -euo pipefail
mac="${1:?Uso: $0 <MAC de Pixilate>}"

command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
sudo apt-get install -y wakeonlan
sudo tailscale up

printf '#!/bin/sh\nexec wakeonlan %s\n' "$mac" | sudo tee /usr/local/bin/wake-pixilate >/dev/null
sudo chmod +x /usr/local/bin/wake-pixilate
echo "Listo: ssh $(hostname) wake-pixilate"
