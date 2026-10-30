# Trabajos largos en Pixilate que sobreviven al cerrar SSH (OpenSSH en Windows mata los procesos de la sesión).
# Corren como tarea programada S4U: sin sesión abierta, sin contraseña guardada, con acceso a la GPU.
#   job.ps1 start <nombre> <carpeta> "<comando>" [-AtStartup]
#   job.ps1 list
#   job.ps1 log <nombre> [-Tail 100]
#   job.ps1 stop <nombre>
param(
    [Parameter(Mandatory)][ValidateSet('start', 'list', 'log', 'stop')][string]$Verb,
    [string]$Name,
    [string]$Dir,
    [string]$Command,
    [int]$Tail = 40,
    # Además de lanzarlo ahora, lo vuelve a lanzar en cada arranque de Windows, sin sesión abierta
    [switch]$AtStartup
)
$ErrorActionPreference = 'Stop'
$root = "$HOME\bakery-jobs"
$task = "bakery-$Name"
if ($Verb -ne 'list' -and -not $Name) { throw 'Falta el nombre del trabajo' }

switch ($Verb) {
    'start' {
        if (-not $Dir -or -not $Command) { throw 'Uso: job.ps1 start <nombre> <carpeta> "<comando>"' }
        $Dir = (Resolve-Path $Dir).Path
        New-Item -ItemType Directory -Force $root | Out-Null
        $log = "$root\$Name.log"
        # El comando va a su propio .ps1 para no pelear con comillas anidadas
        Set-Content "$root\$Name.ps1" -Encoding utf8 -Value @"
`$env:PYTHONUNBUFFERED = '1'
Set-Location '$Dir'
"[bakery] inicio `$(Get-Date -f s)" | Out-File -Encoding utf8 '$log'
& { $Command } *>&1 | Out-File -Append -Encoding utf8 '$log'
"[bakery] fin `$(Get-Date -f s) codigo `$LASTEXITCODE" | Out-File -Append -Encoding utf8 '$log'
"@
        $action = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\$Name.ps1`""
        # En sesiones SSH USERDOMAIN vale WORKGROUP: la cuenta local se nombra con COMPUTERNAME
        $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
        # Sin límite de tiempo (el default corta a las 72 h) y prioridad normal (el default es baja).
        # En una laptop (Aerilate) el default tampoco arranca con batería y mata la tarea al desconectar el cargador
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -Priority 4 `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $trigger = if ($AtStartup) { @{ Trigger = New-ScheduledTaskTrigger -AtStartup } } else { @{} }
        Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings @trigger -Force -ErrorAction Stop | Out-Null  # sin administrador da "Acceso denegado"; sin -ErrorAction seguía y arrancaba la tarea vieja
        Start-ScheduledTask $task
        "Lanzado $task. Log: $log"
    }
    'list' {
        Get-ScheduledTask -TaskName 'bakery-*' -EA SilentlyContinue | ForEach-Object {
            $i = $_ | Get-ScheduledTaskInfo
            [pscustomobject]@{ Nombre = $_.TaskName -replace '^bakery-'; Estado = $_.State; Inicio = $i.LastRunTime; Resultado = $i.LastTaskResult }
        } | Format-Table -AutoSize
    }
    'log' { Get-Content "$root\$Name.log" -Tail $Tail }
    'stop' {
        # Stop-ScheduledTask solo detiene el PowerShell de la tarea y regresa sin esperar: los hijos (python,
        # llama-server) siguen vivos y el log sigue abierto para el siguiente `start`. Se mata el árbol completo.
        $todos = Get-CimInstance Win32_Process
        $raices = @($todos | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$root\$Name.ps1*" })
        # Sin administrador, CommandLine de los procesos de sesión 0 llega vacío: no se ve la raíz y no se mata nada
        if (-not $raices -and (Get-ScheduledTask $task -EA SilentlyContinue).State -eq 'Running') {
            throw "$task corre pero no veo su proceso: repetir stop desde PowerShell de administrador"
        }
        $arbol = $raices
        for ($i = 0; $i -lt $arbol.Count; $i++) {
            $arbol += @($todos | Where-Object { $_.ParentProcessId -eq $arbol[$i].ProcessId })
        }
        # Antes que Stop-ScheduledTask: con el padre muerto, taskkill /T ya no encuentra a los hijos
        # cmd junta stderr: en PowerShell 5.1, 2>&1 de un nativo con ErrorActionPreference Stop lanza excepción
        $salida = foreach ($p in $raices) { cmd /c "taskkill /T /F /PID $($p.ProcessId) 2>&1" }
        Start-Sleep 1
        # Sin administrador, taskkill puede fallar con la tarea en sesión 0 (pasó con una -AtStartup) y el
        # siguiente `start` choca con el proceso vivo: se verifica en vez de confiar en taskkill
        $vivos = @($arbol | Where-Object { Get-Process -Id $_.ProcessId -EA SilentlyContinue })
        if ($vivos) {
            $salida | Write-Warning
            throw "Siguen vivos ($($vivos.ProcessId -join ', ')). Desde PowerShell de administrador: taskkill /T /F /PID $($vivos[0].ProcessId), y repetir stop"
        }
        Stop-ScheduledTask $task
        Unregister-ScheduledTask $task -Confirm:$false
        "Detenido $task"
    }
}
