#!/bin/bash
# Cada 5 s: VRAM, uso de GPU y CPU del servidor Windows y si hay un juego abierto; más las líneas nuevas del vigilante.
#   bash banco/muestreo.sh [host] > muestreo.log     (host de ~/.ssh/config, default pixilate)
# JUEGO: patrón de Get-Process del juego a detectar. CLON: ruta del clon de Bakery relativa al home del servidor.
H="${1:-pixilate}"
JUEGO="${JUEGO:-League*}"
CLON="${CLON:-Desktop\\Personal\\iroFactory\\Bakery}"
J="powershell -NoProfile -ExecutionPolicy Bypass -File $CLON\\remote\\windows\\job.ps1"
ultimo=""
while true; do
  ssh -n "$H" 'nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits | % { "vram,gpu: $_" }; "cpu: " + [int](Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average; "juego: " + ((Get-Process '"$JUEGO"' -EA SilentlyContinue | % Name | Sort-Object -Unique) -join ",")' 2>/dev/null | tr '\n' ' ' | sed "s/^/$(date +%H:%M:%S) /"; echo
  v=$(ssh -n "$H" "$J log bakers-vigilante -Tail 3" 2>/dev/null | grep vigilante | tail -1)
  [ "$v" != "$ultimo" ] && [ -n "$v" ] && echo "$v" && ultimo="$v"
  sleep 5
done
