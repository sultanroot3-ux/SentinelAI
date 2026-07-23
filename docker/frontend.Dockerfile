# SentinelAI frontend — production image (static build served by nginx).
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
# npm ci: reproducible install from the lockfile only
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Default (self-signed / local) config; docker-compose.prod.yml overrides this
# with the Let's Encrypt template rendered by deployment/install_ubuntu.sh.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
# Hot-reload nginx when certbot renews the certificate (C2): official image
# executes /docker-entrypoint.d/*.sh at startup; this one backgrounds a watcher.
COPY docker/nginx-cert-watcher.sh /docker-entrypoint.d/90-cert-watcher.sh
RUN chmod +x /docker-entrypoint.d/90-cert-watcher.sh
EXPOSE 80 443
