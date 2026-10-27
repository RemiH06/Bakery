# Instala llama-swap en Pixilate y lo deja como trabajo de Bakery que vuelve en cada arranque.
# Correr desde la raíz del clon de Bakery en Pixilate:
#   powershell -NoProfile -ExecutionPolicy Bypass -File bakers\pixilate\setup.ps1
# Idempotente: no vuelve a descargar ni cambia la llave si ya existen.
$ErrorActionPreference = 'Stop'
$root = "$env:USERPROFILE\bakers"
$ver = '264'
$zip = "llama-swap_${ver}_windows_amd64.zip"
$rel = "https://github.com/mostlygeek/llama-swap/releases/download/v$ver"
$config = (Resolve-Path "$PSScriptRoot\llama-swap.yaml").Path
$job = (Resolve-Path "$PSScriptRoot\..\..\remote\job.ps1").Path

if (-not (Test-Path "$root\llama-swap\llama-swap.exe")) {
    curl.exe -L --fail -o "$root\$zip" "$rel/$zip"
    $sumas = curl.exe -L --fail "$rel/llama-swap_${ver}_checksums.txt"
    $esperado = ($sumas | Select-String -SimpleMatch $zip).Line.Split(' ')[0]
    if ((Get-FileHash "$root\$zip" -Algorithm SHA256).Hash -ne $esperado) { throw "El checksum de $zip no coincide" }
    Expand-Archive -Force "$root\$zip" "$root\llama-swap"
}

# Llave de API: aleatoria, una sola vez, legible solo por esta cuenta
$key = "$root\api-key.txt"
if (-not (Test-Path $key)) {
    $bytes = [byte[]]::new(36)
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    Set-Content $key -NoNewline -Encoding ascii -Value ('sk-' + [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_'))
    icacls $key /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
}

# La llave entra por variable de entorno del proceso, no por argumento (los argumentos se ven en el administrador de tareas)
$cmd = "`$env:BAKERS_API_KEY = Get-Content '$key' -Raw; .\llama-swap\llama-swap.exe -config '$config' -listen 127.0.0.1:8090"
& $job start bakers $root $cmd -AtStartup

# Solo al tailnet, en su propio puerto HTTPS (el 443 es de otro servicio). Persiste entre reinicios.
tailscale serve --bg --https=8090 http://127.0.0.1:8090
"[bakers] listo. Llave para Aerilate: $key"
