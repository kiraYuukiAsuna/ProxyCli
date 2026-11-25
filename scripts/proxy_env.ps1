param([ValidateRange(1, 65535)][int]$Port = 8080, [switch]$Off)
if ($Off) {
    foreach ($name in @(
        'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
        'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS'
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    Write-Host 'HTTP/HTTPS proxy disabled in this terminal.'
    return
}
$proxyCa = Join-Path $env:USERPROFILE '.http-proxy-toolkit\mitmproxy\mitmproxy-ca-cert.pem'
if (-not (Test-Path -LiteralPath $proxyCa -PathType Leaf)) {
    throw "CA not found: $proxyCa. Start the proxy first."
}
$proxyUrl = "http://127.0.0.1:$Port"
$env:HTTP_PROXY = $proxyUrl
$env:HTTPS_PROXY = $proxyUrl
$env:http_proxy = $proxyUrl
$env:https_proxy = $proxyUrl
$env:SSL_CERT_FILE = $proxyCa
$env:REQUESTS_CA_BUNDLE = $proxyCa
$env:CURL_CA_BUNDLE = $proxyCa
$env:NODE_EXTRA_CA_CERTS = $proxyCa
Write-Host "HTTP/HTTPS proxy: $proxyUrl"
Write-Host "CA: $proxyCa"
