#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local/LAN SentinelAI deployments.
# Production should use real certificates (certbot) instead — see DEPLOYMENT.md.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/docker/certs"
DAYS="${DAYS:-825}"
CN="${CN:-sentinelai.local}"

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days "$DAYS" \
  -keyout "$CERT_DIR/sentinel.key" \
  -out "$CERT_DIR/sentinel.crt" \
  -subj "/CN=$CN" \
  -addext "subjectAltName=DNS:$CN,DNS:localhost,IP:127.0.0.1"

chmod 600 "$CERT_DIR/sentinel.key"
echo "Self-signed cert written to $CERT_DIR (CN=$CN, valid $DAYS days)."
echo "Browsers will warn about self-signed certs — use certbot in production."
