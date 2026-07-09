param(
  [int]$Port = 8000
)

$env:PORT = "$Port"
python -m app.server
