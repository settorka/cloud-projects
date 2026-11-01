$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. 'F:\fx\app\scripts\ssis-runtime.ps1'
$capability=Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if($capability.State -ne 'Installed') {Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null}
Set-Service sshd -StartupType Automatic
Start-Service sshd
$pub=(Get-Content 'F:\fx\app\access\authorized_key.pub' -Raw).Trim()
if($pub -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+(?: .*)?$') {throw 'Invalid public transport key.'}
$keyData=($pub -split ' ')[1]
$path='C:\ProgramData\ssh\administrators_authorized_keys'
$existing=if(Test-Path $path) {@(Get-Content $path | Where-Object {$_ -notmatch [regex]::Escape($keyData)})} else {@()}
$entry='restrict,port-forwarding,permitopen="127.0.0.1:8501",command="cmd.exe /c exit 1" '+$pub
@($existing)+@($entry) | Set-Content $path -Encoding ascii
& icacls $path /inheritance:r /grant '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if($LASTEXITCODE -ne 0) {throw 'SSH key ACL configuration failed.'}
$configPath='C:\ProgramData\ssh\sshd_config'
$config=Get-Content $configPath -Raw
$config=[regex]::Replace($config,'(?m)^\s*#?\s*PasswordAuthentication\s+.*$','PasswordAuthentication no')
$config=[regex]::Replace($config,'(?m)^\s*#?\s*AllowTcpForwarding\s+.*$','AllowTcpForwarding local')
if($config -notmatch '(?m)^PasswordAuthentication no') {throw 'SSH password setting not found.'}
$config | Set-Content $configPath -Encoding ascii
& 'C:\Windows\System32\OpenSSH\sshd.exe' -t
if($LASTEXITCODE -ne 0) {throw 'SSH configuration validation failed.'}
Restart-Service sshd
$hostKey=(Get-Content 'C:\ProgramData\ssh\ssh_host_ed25519_key.pub' -Raw).Trim()
@{host_public_key=$hostKey;forward_target='127.0.0.1:8501';password_authentication=$false;key_is_tunnel_only=$true} | ConvertTo-Json | Set-Content 'F:\fx\ssh-host.json' -Encoding UTF8
$context=Get-FxBlobContext
Send-FxArtifact $context 'access/ssh-host.json' 'F:\fx\ssh-host.json'
Write-Output 'SSH ready: key-only, tunnel-only key, local dashboard target only.'
