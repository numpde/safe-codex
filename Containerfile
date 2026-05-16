FROM node:24-bookworm-slim

ARG CODEX_VERSION=0.130.0

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    less \
    openssh-client \
    ripgrep \
  && rm -rf /var/lib/apt/lists/*

# Build-time npm is used only to assemble the runtime image. Lifecycle scripts
# are disabled, and npm/npx/corepack are removed from the final runtime PATH.
RUN npm install -g "@openai/codex@${CODEX_VERSION}" --ignore-scripts --no-audit --no-fund \
  && npm cache clean --force \
  && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
  && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /root/.npm /tmp/*

RUN mkdir -p /workspace /home/codex/.codex /home/codex/.cache /home/codex/.local/share \
  && chown -R node:node /workspace /home/codex

USER node
ENV HOME=/home/codex
ENV SHELL=/bin/bash
WORKDIR /workspace

ENTRYPOINT ["codex"]
