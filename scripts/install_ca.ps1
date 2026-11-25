param(
    [string]$CertPath = (Join-Path $env:USERPROFILE '.http-proxy-toolkit\mitmproxy\mitmproxy-ca-cert.pem'),
    [switch]$System,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $CertPath -PathType Leaf)) {
    throw "CA certificate not found: $CertPath. Start the proxy once first (.\scripts\start_proxy.ps1) to generate the CA, or pass -CertPath."
}

$certutil = (Get-Command certutil.exe -ErrorAction Stop).Source
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertPath)
try {
    $thumbprint = $cert.Thumbprint
} finally {
    $cert.Dispose()
}
$storeLabel = if ($System) { 'LocalMachine\Root' } else { 'CurrentUser\Root' }

if ($Uninstall) {
    if ($System) {
        & $certutil -delstore Root $thumbprint
    } else {
        & $certutil -user -delstore Root $thumbprint
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove CA certificate from $storeLabel (exit code: $LASTEXITCODE)."
    }
    Write-Host "CA certificate removed from ${storeLabel}: $CertPath (Thumbprint: $thumbprint)"
    exit 0
}

if ($System) {
    & $certutil -addstore Root $CertPath
} else {
    & $certutil -user -addstore Root $CertPath
}
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install CA certificate into $storeLabel (exit code: $LASTEXITCODE)."
}
Write-Host "CA certificate installed in ${storeLabel}: $CertPath (Thumbprint: $thumbprint)"
