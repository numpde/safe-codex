#!/bin/sh
set -eu
mkdir -p "$HOME/.pi/agent"
cp /opt/safe-pi/policy/models.json /opt/safe-pi/policy/settings.json "$HOME/.pi/agent/"
node /opt/safe-pi/bridge.mjs &
case "${SAFE_PI_WORKSPACE_MODE:-copy}" in
  copy)
    system_prompt=$(cat /opt/safe-pi/policy/system.md)
    tools=read,bash,edit,write,grep,find,ls
    ;;
  ro)
    system_prompt=$(cat /opt/safe-pi/policy/system-ro.md)
    tools=read,bash,grep,find,ls
    ;;
  *)
    echo "Unsupported workspace mode" >&2
    exit 2
    ;;
esac
if [ "${SAFE_PI_QUALIFICATION:-0}" = 1 ]; then
  system_prompt="$system_prompt

$(cat /opt/safe-pi/policy/qualification.md)"
fi
exec node /opt/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js \
  --provider local --model "${SAFE_PI_MODEL:-qwen3.8-27b}" --thinking xhigh \
  --no-extensions --no-skills --no-context-files --no-approve \
  --no-prompt-templates --no-themes \
  --tools "$tools" \
  --session-dir /sessions \
  --append-system-prompt "$system_prompt" "$@"
