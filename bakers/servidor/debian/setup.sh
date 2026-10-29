#!/usr/bin/env bash
# Instala llama-swap en Debian (servidor propio, nube, WSL o una Pi) y lo deja como servicio de systemd que vuelve solo.
# Correr desde la raíz del clon de Bakery, con la cuenta que va a correr los modelos (pide sudo para systemd):
#   bash bakers/servidor/debian/setup.sh
# Idempotente: no vuelve a descargar ni cambia las llaves si ya existen. Volver a correrlo es el reinicio limpio.
#
# Variables opcionales:
#   BAKERS_LLAMA_SERVER, BAKERS_PRISM_SERVER, BAKERS_WHISPER_SERVER  binarios ya compilados, relativos a ~/bakers o
#       absolutos (default: llama.cpp/build/bin/llama-server, llama.cpp-prism/build/bin/llama-server,
#       whisper.cpp/build/bin/whisper-server)
#   BAKERS_PUERTO=8090    dónde escucha llama-swap (siempre en 127.0.0.1)
#   BAKERS_VIGILANTE=1    instala el vigilante de marchas: solo si la máquina se comparte con otra carga de GPU
set -euo pipefail
servidor="$(cd "$(dirname "$0")/.." && pwd)"
root="$HOME/bakers"
puerto="${BAKERS_PUERTO:-8090}"
llama="${BAKERS_LLAMA_SERVER:-llama.cpp/build/bin/llama-server}"
prism="${BAKERS_PRISM_SERVER:-llama.cpp-prism/build/bin/llama-server}"
whisper="${BAKERS_WHISPER_SERVER:-whisper.cpp/build/bin/whisper-server}"
ver=264
arq="$(dpkg --print-architecture)"  # amd64 o arm64, las dos tienen binario oficial
tgz="llama-swap_${ver}_linux_${arq}.tar.gz"
rel="https://github.com/mostlygeek/llama-swap/releases/download/v$ver"

mkdir -p "$root"
cd "$root"

if [ ! -x llama-swap/llama-swap ]; then
    curl -fL -o "$tgz" "$rel/$tgz"
    curl -fL "$rel/llama-swap_${ver}_checksums.txt" | grep " $tgz\$" | sha256sum -c -
    mkdir -p llama-swap
    tar -xzf "$tgz" -C llama-swap
fi

# Llaves de API: aleatorias, una sola vez, legibles solo por esta cuenta. Una por cliente, para revocar solo la que
# se filtre (Aerilate y la Pi pública). Mismo formato que las de Windows.
for llave in api-key.txt api-key-pi.txt; do
    if [ ! -f "$llave" ]; then
        (umask 077; printf 'sk-%s' "$(head -c 36 /dev/urandom | base64 | tr '+/' '-_')" > "$llave")
    fi
    chmod 600 "$llave"
done

for b in "$llama" "$prism" "$whisper"; do
    case "$b" in /*) ruta="$b" ;; *) ruta="$root/$b" ;; esac
    [ -x "$ruta" ] || echo "[bakers] aviso: no existe $ruta; los modelos que lo usan van a fallar al cargarse" >&2
done

# Las unidades se generan desde las plantillas con las rutas de esta máquina
instala() {
    sed -e "s|@USUARIO@|$USER|g" -e "s|@ROOT@|$root|g" -e "s|@SERVIDOR@|$servidor|g" -e "s|@PUERTO@|$puerto|g" \
        -e "s|@LLAMA@|$llama|g" -e "s|@PRISM@|$prism|g" -e "s|@WHISPER@|$whisper|g" \
        "$servidor/debian/$1" | sudo tee "/etc/systemd/system/$1" >/dev/null
}
instala bakers.service
if [ "${BAKERS_VIGILANTE:-0}" = 1 ]; then
    sudo apt-get install -y python3-psutil
    instala bakers-vigilante.service
fi
sudo systemctl daemon-reload
# restart y no solo start: si ya corría, así toma la unidad nueva. systemd mata también a los llama-server hijos.
sudo systemctl enable bakers.service
sudo systemctl restart bakers.service
if [ "${BAKERS_VIGILANTE:-0}" = 1 ]; then
    sudo systemctl enable bakers-vigilante.service
    sudo systemctl restart bakers-vigilante.service
elif [ -f /etc/systemd/system/bakers-vigilante.service ]; then
    sudo systemctl disable --now bakers-vigilante.service
fi

# Solo al tailnet, si esta máquina está en él (en WSL, el nodo de Tailscale es el Windows de fuera)
if command -v tailscale >/dev/null && tailscale status >/dev/null 2>&1; then
    sudo tailscale serve --bg --https="$puerto" "http://127.0.0.1:$puerto"
else
    echo "[bakers] sin Tailscale aquí: llama-swap solo responde en 127.0.0.1:$puerto" >&2
fi
echo "[bakers] listo. Llave para Aerilate: $root/api-key.txt. Log: journalctl -u bakers -f"
