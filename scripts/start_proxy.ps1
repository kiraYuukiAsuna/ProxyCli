param(
    [ValidateRange(1, 65535)][int]$Port = 8080,
    [switch]$Web,
    [ValidateRange(1, 65535)][int]$WebPort = 8081,
    [ValidateRange(0, 4)][int]$FlowDetail = 0
)
$ErrorActionPreference = 'Stop'
if ($PSBoundParameters.ContainsKey('WebPort')) {
    $Web = $true
}
if ($Web -and $PSBoundParameters.ContainsKey('FlowDetail')) {
    throw '-FlowDetail cannot be used together with -Web.'
}
if ($Web -and $WebPort -eq $Port) {
    throw 'WebPort must be different from Port.'
}
$toolkitDir = Split-Path -Parent $PSScriptRoot
$proxyCaDir = Join-Path $env:USERPROFILE '.http-proxy-toolkit\mitmproxy'
$addon = Join-Path $toolkitDir 'assets\http_proxy\add_header.py'
if ($Web) {
    $proxyBin = (Get-Command mitmweb -ErrorAction Stop).Source
} else {
    $proxyBin = (Get-Command mitmdump -ErrorAction Stop).Source
}
New-Item -ItemType Directory -Force -Path $proxyCaDir | Out-Null
Write-Host "Proxy: http://127.0.0.1:$Port (foreground; Ctrl+C to stop)"
if ($Web) {
    Write-Host "Web UI: http://127.0.0.1:$WebPort (open the URL printed by mitmweb below)"
} elseif ($FlowDetail -gt 0) {
    Write-Host "Flow detail: $FlowDetail"
}
Write-Host "CA: $proxyCaDir\mitmproxy-ca-cert.pem"
Write-Host "In your client terminal: . .\scripts\proxy_env.ps1 -Port $Port"
Write-Host 'Disable proxy: . .\scripts\proxy_env.ps1 -Off'
if ($Web) {
    & $proxyBin --listen-host 127.0.0.1 --listen-port $Port --web-host 127.0.0.1 --web-port $WebPort --set "confdir=$proxyCaDir" -s $addon
} else {
    & $proxyBin --listen-host 127.0.0.1 --listen-port $Port --set "confdir=$proxyCaDir" --flow-detail $FlowDetail -s $addon
}
exit $LASTEXITCODE
