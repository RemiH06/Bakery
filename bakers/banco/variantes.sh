#!/bin/bash
# Para cada variante: levanta llama-server en el servidor Windows (:10099, por túnel), corre banco_vision.py y lo mata.
#   REELS="<código> <código>" bash banco/variantes.sh variantes.txt [host]
# variantes.txt: una línea por variante, `etiqueta|flags extra de llama-server` (p. ej. `nooff|--no-op-offload`).
# Logs de cada servidor en ~/.bakers/banco/.
S="$(cd "$(dirname "$0")" && pwd)"
H="${2:-pixilate}"
SALIDA="$HOME/.bakers/banco"; mkdir -p "$SALIDA"
BASE='-c 32768 -np 1 -fa on --reasoning off --no-webui -ngl 99 -m models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf --mmproj models\mmproj-Qwen3.6-35B-A3B-F16.gguf'
matar() {
  ssh -n "$H" 'Get-Process llama-server -EA SilentlyContinue | Where-Object { (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like "*10099*" } | Stop-Process -Force'
}
while IFS='|' read -r etiqueta flags; do
  [ -z "$etiqueta" ] && continue
  log="$SALIDA/server_$etiqueta.log"
  ssh -n -o ExitOnForwardFailure=yes -L 10099:127.0.0.1:10099 "$H" \
    "cd ~\\bakers; llama.cpp\\llama-server.exe --host 127.0.0.1 --port 10099 $BASE $flags 2>&1" > "$log" 2>&1 &
  tunel=$!
  for i in $(seq 1 300); do grep -qE "listening|error|failed|Could not" "$log" && break; sleep 1; done
  if grep -q listening "$log"; then
    echo "== $etiqueta VRAM: $(ssh -n "$H" 'nvidia-smi --query-gpu=memory.used --format=csv,noheader')"
    (cd "$S/.."
     VARIANTES="${VARIANTES:-8x540}" uv run python banco/banco_vision.py "$etiqueta" 10099 $REELS < /dev/null 2>&1 | grep -v "^$")
  else
    echo "== $etiqueta no arrancó:"; tail -5 "$log"
  fi
  matar; kill $tunel 2>/dev/null; wait $tunel 2>/dev/null; sleep 3
done < "$1"
