#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BUILD=$ROOT/.build
BASE_TAG=safe-pi-node:24-83f1c388
BASE_ID=sha256:c10884952bb8c37122fcc3fe6f97af3ab0a80e5eb02ee5df707406b4e11a7e3e
PYTHON_IMAGE=python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
HELPER=${PROART_WLAN_HELPER:-$HOME/repos/proart-llm/vllm/wlan-download.py}
mode=${1:---offline}
[[ $# -le 1 && ( $mode == --offline || $mode == --prepare ) ]] || { echo 'Usage: build.sh [--offline|--prepare]' >&2; exit 2; }
[[ $(id -u) == 1000 && $(id -g) == 1000 ]] || { echo 'This experiment requires host UID/GID 1000.' >&2; exit 1; }
mkdir -p "$BUILD/base" "$BUILD/packages"
exec 9>"$BUILD/build.lock"
flock -n 9 || { echo 'Another build is active.' >&2; exit 1; }
name=safe-pi-build-$(cat /proc/sys/kernel/random/uuid)
volume=$name-socket
cleanup() {
  timeout 15 docker rm -f "$name-proxy" "$name-prepare" "$name-base" >/dev/null 2>&1 || true
  timeout 15 docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT
common=(--rm --pull never --read-only --user 1000:1000 --cap-drop ALL
        --security-opt no-new-privileges --memory 2g --memory-swap 2g --cpus 2 --pids-limit 128)
actual=$(docker image inspect --format '{{.Id}}' "$BASE_TAG" 2>/dev/null || true)
if [[ $actual != "$BASE_ID" ]]; then
  if [[ $mode == --prepare ]]; then
    docker image inspect "$PYTHON_IMAGE" >/dev/null
    test -f "$HELPER"
    docker run "${common[@]}" --name "$name-base" --network host \
      --mount "type=bind,src=$HELPER,dst=/bootstrap/wlan-download.py,readonly" \
      --mount "type=bind,src=$ROOT/prepare-base.py,dst=/prepare.py,readonly" \
      --mount "type=bind,src=$BUILD/base,dst=/output" \
      "$PYTHON_IMAGE" python -B -u /prepare.py
  fi
  docker load --input "$BUILD/base/image/vllm.tar" >/dev/null
fi
[[ $(docker image inspect --format '{{.Id}}' "$BASE_TAG") == "$BASE_ID" ]] || { echo 'Base image identity mismatch.' >&2; exit 1; }
if [[ $mode == --prepare ]]; then
  docker image inspect "$PYTHON_IMAGE" >/dev/null
  docker volume create "$volume" >/dev/null
  docker run --rm --pull never --network none --read-only --cap-drop ALL --cap-add CHOWN \
    --security-opt no-new-privileges --mount "type=volume,src=$volume,dst=/relay" \
    "$PYTHON_IMAGE" sh -c 'chmod 700 /relay && chown 1000:1000 /relay'
  docker run -d "${common[@]}" --name "$name-proxy" --network host \
    --mount "type=volume,src=$volume,dst=/relay" \
    --mount "type=bind,src=$ROOT/wlan-proxy.py,dst=/proxy.py,readonly" \
    "$PYTHON_IMAGE" python -B -u /proxy.py >/dev/null
  for attempt in {1..20}; do
    if docker exec "$name-proxy" test -S /relay/build.sock; then break; fi
    sleep 0.2
  done
  docker exec "$name-proxy" test -S /relay/build.sock
  docker run "${common[@]}" --name "$name-prepare" --network none \
    --tmpfs /tmp:rw,nosuid,nodev,size=512m --env HOME=/tmp \
    --mount "type=volume,src=$volume,dst=/relay,readonly" \
    --mount "type=bind,src=$ROOT,dst=/scripts,readonly" \
    --mount "type=bind,src=$BUILD/packages,dst=/output" \
    "$BASE_TAG" sh /scripts/prepare-packages.sh
fi
for kind in apk app; do
  docker run "${common[@]}" --network none \
    --mount "type=bind,src=$ROOT,dst=/scripts,readonly" \
    --mount "type=bind,src=$BUILD/packages,dst=/output,readonly" \
    "$BASE_TAG" node /scripts/verify-inputs.mjs "$kind"
done
docker build --network none --pull=false --tag safe-pi:0.86.1 \
  --build-arg "NODE_IMAGE=$BASE_TAG" --file "$ROOT/Containerfile" "$ROOT"
docker run "${common[@]}" --network none \
  --tmpfs /workspace:rw,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --tmpfs /home/pi:rw,nosuid,nodev,size=32m,uid=1000,gid=1000 \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --mount "type=bind,src=$ROOT/test-tools.mjs,dst=/test-tools.mjs,readonly" \
  --entrypoint node safe-pi:0.86.1 /test-tools.mjs
docker image inspect --format '{{.Id}}' safe-pi:0.86.1 > "$BUILD/runtime-image-id"
printf 'Built pinned Pi image: %s\n' "$(cat "$BUILD/runtime-image-id")"
