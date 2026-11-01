$ErrorActionPreference='Stop'
Get-NetTCPConnection -State Listen -LocalPort 22 | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json
Get-NetFirewallRule -Name '*OpenSSH*' -ErrorAction SilentlyContinue | Select-Object Name,Enabled,Profile,Direction,Action | ConvertTo-Json
& 'C:\Windows\System32\OpenSSH\sshd.exe' -T | Select-String 'passwordauthentication|allowtcpforwarding|pubkeyauthentication|listenaddress'
Get-WinEvent -LogName 'OpenSSH/Operational' -MaxEvents 8 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Message | ConvertTo-Json
