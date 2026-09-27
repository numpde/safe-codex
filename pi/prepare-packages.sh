#!/bin/sh
set -eu
export BRIDGE_SOCKET=/relay/build.sock BRIDGE_PORT=31828 BRIDGE_CONNECT=1
node /scripts/bridge.mjs &
bridge_pid=$!
trap 'kill "$bridge_pid" 2>/dev/null || true' EXIT
attempt=0
until node -e 'const s=require("net").connect(31828,"127.0.0.1",()=>{s.end();process.exit(0)});s.on("error",()=>process.exit(1))'; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 10 ] || exit 1
  sleep 1
done
export http_proxy=http://127.0.0.1:31828 https_proxy=http://127.0.0.1:31828
export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy"
export npm_config_proxy="$http_proxy" npm_config_https_proxy="$https_proxy"
mkdir -p /output/apk /output/app /tmp/apk-cache
apk --update-cache --cache-dir /tmp/apk-cache fetch --recursive --output /output/apk $(node -p 'JSON.parse(require("fs").readFileSync("/scripts/apk.lock.json")).map(x=>x.package).join(" ")')
node /scripts/verify-inputs.mjs apk
cd /output/app
cp /scripts/package.json /scripts/package-lock.json .
npm ci --ignore-scripts --no-audit --no-fund
npm ls --depth=0
node /scripts/verify-inputs.mjs app
