# Instala llama-swap en Windows (Pixilate) y lo deja como trabajo de Bakery que vuelve en cada arranque.
# Es la variante para una máquina compartida con juegos: prioridad baja y vigilante de marchas.
# Correr desde la raíz del clon de Bakery, en una PowerShell de administrador (la tarea S4U lo pide):
#   powershell -NoProfile -ExecutionPolicy Bypass -File bakers\servidor\windows\setup.ps1
# Idempotente: no vuelve a descargar ni cambia la llave si ya existen.
# Espera los binarios ya compilados en ~\bakers: llama.cpp\, llama.cpp-prism\ y whisper.cpp\Release\.
$ErrorActionPreference = 'Stop'
$root = "$env:USERPROFILE\bakers"
$ver = '264'
$zip = "llama-swap_${ver}_windows_amd64.zip"
$rel = "https://github.com/mostlygeek/llama-swap/releases/download/v$ver"
$config = (Resolve-Path "$PSScriptRoot\..\llama-swap.yaml").Path
$vigilante = (Resolve-Path "$PSScriptRoot\..\vigilante.py").Path
$job = (Resolve-Path "$PSScriptRoot\..\..\..\remote\windows\job.ps1").Path

if (-not (Test-Path "$root\llama-swap\llama-swap.exe")) {
    curl.exe -L --fail -o "$root\$zip" "$rel/$zip"
    $sumas = curl.exe -L --fail "$rel/llama-swap_${ver}_checksums.txt"
    $esperado = ($sumas | Select-String -SimpleMatch $zip).Line.Split(' ')[0]
    if ((Get-FileHash "$root\$zip" -Algorithm SHA256).Hash -ne $esperado) { throw "El checksum de $zip no coincide" }
    Expand-Archive -Force "$root\$zip" "$root\llama-swap"
}

# uv corre el vigilante con su dependencia (psutil) sin tocar el Python del sistema
if (-not (Get-Command uv -EA SilentlyContinue)) {
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
}
$uv = (Get-Command uv).Source  # ruta completa: la tarea S4U no garantiza el PATH de la sesión

# Llaves de API: aleatorias, una sola vez, legibles solo por esta cuenta. Una por cliente, para revocar
# solo la que se filtre: Aerilate y la Pi pública (frambuesa-yi, `tag:publico` en Tailscale).
function Llave($key) {
    if (-not (Test-Path $key)) {
        $bytes = [byte[]]::new(36)
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        Set-Content $key -NoNewline -Encoding ascii -Value ('sk-' + [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_'))
        # Con el nombre de la máquina: la cuenta se llama igual que el equipo y "Pixilate2" a secas resuelve al equipo
        icacls $key /inheritance:r /grant:r "${env:COMPUTERNAME}\${env:USERNAME}:(R,W)" | Out-Null
    }
}
$key = "$root\api-key.txt"
$keyPi = "$root\api-key-pi.txt"
Llave $key
Llave $keyPi

# Las llaves entran por variable de entorno del proceso, no por argumento (los argumentos se ven en el administrador de tareas).
# Los binarios también: llama-swap.yaml es común a Windows y Linux y los toma de ahí.
# Prioridad baja, que heredan llama-swap y cada llama-server: con los expertos de Qwen en CPU, generar la
# satura y un juego bajaba de 120 a 40 FPS (1.0n). Sin juego no cuesta nada: la CPU libre se usa igual.
$cmd = "(Get-Process -Id `$PID).PriorityClass = 'BelowNormal'; " +
    "`$env:BAKERS_API_KEY = Get-Content '$key' -Raw; `$env:BAKERS_API_KEY_PI = Get-Content '$keyPi' -Raw; " +
    "`$env:BAKERS_LLAMA_SERVER = 'llama.cpp/llama-server.exe'; `$env:BAKERS_PRISM_SERVER = 'llama.cpp-prism/llama-server.exe'; " +
    "`$env:BAKERS_WHISPER_SERVER = 'whisper.cpp/Release/whisper-server.exe'; " +
    ".\llama-swap\llama-swap.exe -config '$config' -listen 127.0.0.1:8090 -watch-config"
# Reinicio limpio: `job.ps1 stop` no mata a los hijos y un llama-server huérfano se queda con la VRAM
if (Get-ScheduledTask 'bakery-bakers' -EA SilentlyContinue) {
    & $job stop bakers
    Stop-Process -Name llama-swap, llama-server, whisper-server -Force -EA SilentlyContinue
}
& $job start bakers $root $cmd -AtStartup

# Vigilante de marchas (común con Linux), en el mismo proceso de la tarea para que `stop` sí lo detenga
if (Get-ScheduledTask 'bakery-bakers-vigilante' -EA SilentlyContinue) { & $job stop bakers-vigilante }
& $job start bakers-vigilante $root "& '$uv' run -q --script '$vigilante'" -AtStartup

# Solo al tailnet, en su propio puerto HTTPS (el 443 es de otro servicio). Persiste entre reinicios.
tailscale serve --bg --https=8090 http://127.0.0.1:8090
"[bakers] listo. Llave para Aerilate: $key"
