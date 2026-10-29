#Requires -RunAsAdministrator
# Prepara Pixilate para recibir SSH desde Aerilate por Tailscale y despertar por Wake-on-LAN.
# Correr en Pixilate, PowerShell como administrador. Idempotente: se puede repetir.
param([string]$PublicKeyFile = "$PSScriptRoot\..\aerilate.pub")
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $PublicKeyFile)) { throw "No existe $PublicKeyFile (copia ahí el id_ed25519.pub de Aerilate)" }
$key = (Get-Content $PublicKeyFile -Raw).Trim()

# 1. OpenSSH Server
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd  # el primer arranque genera sshd_config y las llaves del host

# 2. Llave de Aerilate. Para cuentas de administrador sshd solo lee este archivo, no ~/.ssh/authorized_keys
$auth = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $auth) -or -not (Select-String -Path $auth -SimpleMatch $key -Quiet)) {
    Add-Content -Path $auth -Value $key -Encoding ascii
}
icacls $auth /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null  # Administradores y SYSTEM, por SID para Windows en español

# 3. Solo llave, sin contraseña. PowerShell como shell por defecto
$cfg = "$env:ProgramData\ssh\sshd_config"
$lines = Get-Content $cfg
if ($lines -match '^#?\s*PasswordAuthentication\s') {
    $lines = $lines -replace '^#?\s*PasswordAuthentication\s+\w+', 'PasswordAuthentication no'
} else {
    $lines = @('PasswordAuthentication no') + $lines
}
Set-Content -Path $cfg -Value $lines -Encoding ascii
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
    -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" | Out-Null
Restart-Service sshd

# 4. Firewall: el puerto 22 solo acepta conexiones desde la red de Tailscale (100.64.0.0/10)
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
}
Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -RemoteAddress '100.64.0.0/10' -Profile Any

# 5. Tailscale en modo desatendido: sigue conectado aunque nadie inicie sesión después de un WoL
$ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
if (-not (Test-Path $ts)) {
    winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
}
& $ts up --unattended  # la primera vez imprime una URL para iniciar sesión

# 6. Sin suspensión automática conectada a corriente: si se duerme, deja de responder por SSH
powercfg /change standby-timeout-ac 0

# 7. Wake-on-LAN (opcional, para cuando haya una Pi que la despierte). Si no hay cable, solo avisa
$nic = Get-NetAdapter -Physical | Where-Object { $_.MediaType -eq '802.3' } | Select-Object -First 1
if (-not $nic) {
    Write-Warning 'Sin adaptador Ethernet: se omite WoL (SSH funciona igual)'
} else {
    if ($nic.Status -ne 'Up') { Write-Warning "$($nic.Name) no está conectado: WoL no funciona por Wi-Fi" }
    Set-NetAdapterPowerManagement -Name $nic.Name -WakeOnMagicPacket Enabled
    foreach ($kw in '*WakeOnMagicPacket', 'S5WakeOnLan') {  # nombres del driver Realtek; otros drivers pueden no tenerlos
        try { Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword $kw -RegistryValue 1 }
        catch { Write-Warning "El driver no expone $kw; revisa sus propiedades avanzadas a mano" }
    }
    # El inicio rápido deja la tarjeta de red sin energía al apagar y rompe el WoL
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value 0
}

Write-Host ''
Write-Host "Listo. Usuario SSH: $env:USERNAME"
Write-Host "IP de Tailscale:  $(& $ts ip -4)"
if ($nic) {
    Write-Host "MAC para WoL:     $($nic.MacAddress -replace '-', ':')"
    Write-Host 'WoL falta en BIOS (Asus B550): Advanced > APM > ErP Ready = Disabled y Power On By PCI-E = Enabled'
}
