# Image for the `assets` compose service: Node 22 LTS with npm pinned to the
# version in package.json ("packageManager" / "engines"), so the lockfile is
# generated and installed by the same npm. .npmrc has engine-strict=true, so
# any other npm version refuses to install.
FROM node:22-alpine

RUN npm install -g npm@11.6.2 --no-audit --no-fund --loglevel=error \
    && npm --version | grep -qx 11.6.2

ENV NPM_CONFIG_UPDATE_NOTIFIER=false

USER node
WORKDIR /app/frontend
