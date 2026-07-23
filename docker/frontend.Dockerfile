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
EXPOSE 80 443
