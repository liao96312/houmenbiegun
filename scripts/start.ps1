param(
  [int]$Port = 8000,
  # Listen address; default is local-only. Pass -BindHost 0.0.0.0 for LAN access.
  [string]$BindHost = "127.0.0.1"
)

$env:PORT = "$Port"
$env:HOST = "$BindHost"
python -m app.server
