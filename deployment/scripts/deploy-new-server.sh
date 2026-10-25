#!/usr/bin/env bash
# New deployment only. Refuses existing container, existing state, or occupied port.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ${1:-} != --start ]]; then
  echo 'Usage: sudo bash scripts/deploy-new-server.sh --start'
  echo 'Initializes empty local state and starts Snow Console on localhost:8317.'
  exit 0
fi
[[ $(uname -m) == x86_64 ]] || { echo 'The archived image/plugins require Linux amd64.' >&2; exit 1; }
command -v docker >/dev/null
command -v python3 >/dev/null
docker info >/dev/null
docker compose version >/dev/null
if docker container inspect cli-proxy-api >/dev/null 2>&1; then
  echo 'cli-proxy-api already exists. Existing service left unchanged.' >&2; exit 1
fi
for item in config.yaml .env state; do
  [[ ! -e "$ROOT/deploy/$item" ]] || { echo "Existing deploy/$item found; refusing overwrite." >&2; exit 1; }
done
python3 - <<'PY'
import socket
with socket.socket() as s:
    try:s.bind(('127.0.0.1',8317))
    except OSError:raise SystemExit('Local port 8317 is occupied. Nothing was stopped.')
PY
python3 "$ROOT/scripts/verify_portable.py"
docker image load --input "$ROOT/images/cpa-v8.0.31-linux-amd64.tar.gz"
docker image inspect eceasy/cli-proxy-api:v8.0.31 --format '{{json .}}' | python3 -c '
import json,sys
d=json.load(sys.stdin)
expected="sha256:db1812ea5fc703ae228ef53e75e03f502211a2c9194cc2e8152000d4b974da74"
config="sha256:b35e4e90159cb14f2c35c1bec89bd6a923effb68b8081aef4ec94d20ef992224"
assert d["Os"]=="linux" and d["Architecture"]=="amd64", "Wrong image platform"
assert d["Id"] in (expected,config) or any(x.endswith("@"+expected) for x in d.get("RepoDigests",[])), "Unexpected image identity"
'
python3 "$ROOT/scripts/prepare_deployment.py"
cd "$ROOT/deploy"
# A verified local tag is used after load; --pull never prevents an implicit registry update.
docker compose -f docker-compose.yml -f docker-compose.snow.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.snow.yml up -d --no-build --pull never
docker compose -f docker-compose.yml -f docker-compose.snow.yml ps
echo 'Ready at server localhost:8317. Credentials are stored privately in deploy/.env.'
echo 'Import OAuth accounts and bind their proxies before sending model requests.'
