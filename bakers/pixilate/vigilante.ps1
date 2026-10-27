# Vigilante de los Bakers: cada 5 s mira la VRAM y elige la marcha más alta que cabe (perfil de llama-swap).
# Baja al momento, sube solo tras un minuto estable y nunca descarga un modelo a media respuesta.
# Lo lanza setup.ps1 como trabajo `bakers-vigilante` al arrancar Windows.
#   -Extra 3000 -Duracion 60   simula 3 GB ocupados por otro programa durante un minuto (prueba sin abrir un juego)
param([int]$Extra = 0, [int]$Duracion = 0)
$ErrorActionPreference = 'Stop'
$api = 'http://127.0.0.1:8090'
$auth = @{ Authorization = "Bearer $((Get-Content "$env:USERPROFILE\bakers\api-key.txt" -Raw).Trim())" }
# VRAM propia de cada modelo con -c 32768, en MiB, sin lo del escritorio (medida el 2026-10-27)
$marchas = @(
    @{ perfil = 'alta'; modelo = 'bonsai'; vram = 9100 },
    @{ perfil = 'media'; modelo = 'qwen'; vram = 3350 },
    @{ perfil = 'ninguna'; modelo = $null; vram = 0 }
)
$margen = 1024    # MiB libres para que lo demás (el juego) no se quede corto
$subirTras = 60   # segundos cabiendo sin interrupción antes de subir a esa marcha
# shortcut: solo vigila VRAM; Qwen también pide ~20 GB de RAM y un juego pesado con WSL encendido podría no caber. Medir RAM con un juego abierto.
$cabeDesde = @{}
$fin = if ($Duracion) { (Get-Date).AddSeconds($Duracion) } else { [datetime]::MaxValue }

function Log($msg) { "[vigilante] $(Get-Date -f s) $msg" }

while ((Get-Date) -lt $fin) {
    try {
        $usado, $total = (nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits) -split ',\s*' | ForEach-Object { [int]$_ }
        $corriendo = @((Invoke-RestMethod "$api/running" -Headers $auth).running)
        $cargado = $marchas | Where-Object { $_.modelo -and $_.modelo -in $corriendo.model } | Select-Object -First 1
        # Lo que usa todo lo demás: el total menos lo que ocupa nuestro modelo cargado
        $otros = $usado + $Extra - $(if ($cargado) { $cargado.vram } else { 0 })
        $activo = (Invoke-RestMethod "$api/api/profiles" -Headers $auth).active
        $iActual = @(0..2 | Where-Object { $marchas[$_].perfil -eq $activo })[0]

        $ahora = Get-Date
        $nuevo = $null
        for ($i = 0; $i -lt $marchas.Count; $i++) {
            $m = $marchas[$i]
            $cabe = ($m.vram -eq 0) -or ($m.vram + $otros + $margen -le $total)
            if (-not $cabe) { $cabeDesde.Remove($m.perfil); continue }
            if (-not $cabeDesde.ContainsKey($m.perfil)) { $cabeDesde[$m.perfil] = $ahora }
            # Bajar o quedarse: inmediato. Subir: solo si lleva un minuto cabiendo.
            $estable = ($ahora - $cabeDesde[$m.perfil]).TotalSeconds -ge $subirTras
            if ($null -eq $iActual -or $i -ge $iActual -or $estable) { $nuevo = $i; break }
        }

        if ($nuevo -ne $iActual) {
            $body = @{ name = $marchas[$nuevo].perfil } | ConvertTo-Json
            Invoke-RestMethod -Method Put "$api/api/profiles/active" -Headers $auth -Body $body -ContentType 'application/json' | Out-Null
            Log "marcha $activo -> $($marchas[$nuevo].perfil) (otros usan $otros de $total MiB)"
        }

        # Un modelo por encima de la marcha permitida se descarga, pero nunca a media respuesta
        if ($cargado -and [array]::IndexOf($marchas, $cargado) -lt $nuevo) {
            $proxy = ($corriendo | Where-Object { $_.model -eq $cargado.modelo }).proxy
            if (-not (@(Invoke-RestMethod "$proxy/slots") | Where-Object { $_.is_processing })) {
                Invoke-RestMethod -Method Post "$api/api/models/unload/$($cargado.modelo)" -Headers $auth | Out-Null
                Log "descargado $($cargado.modelo)"
            }
        }
    }
    catch { Log "sin llama-swap o error: $($_.Exception.Message)" }
    Start-Sleep 5
}
