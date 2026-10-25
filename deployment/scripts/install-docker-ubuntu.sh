#!/usr/bin/env bash
# For a NEW Ubuntu 22.04 amd64 host only. Never run on the existing production host.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ${1:-} != --install ]]; then
  echo 'Usage: sudo bash scripts/install-docker-ubuntu.sh --install'
  echo 'Installs the five archived Docker packages on a new Ubuntu 22.04 amd64 host.'
  exit 0
fi
[[ $EUID -eq 0 ]] || { echo 'Run as root or with sudo.' >&2; exit 1; }
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(dpkg --print-architecture) == amd64 ]] || {
  echo 'This archived installer supports Ubuntu 22.04 amd64 only.' >&2; exit 1;
}
if command -v docker >/dev/null 2>&1; then
  echo 'Docker already exists. Existing installation left unchanged.' >&2; exit 1
fi
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
    echo "Conflicting package $package exists; nothing was uninstalled." >&2; exit 1
  fi
done
python3 "$ROOT/scripts/verify_portable.py"
# Ubuntu dependencies may need network access. Docker itself comes from verified local .deb files.
apt-get install -y --no-install-recommends "$ROOT"/docker-packages/ubuntu-22.04-amd64/*.deb
docker version --format '{{.Server.Version}}'
docker compose version --short
