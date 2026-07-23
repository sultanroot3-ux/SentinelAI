#!/bin/sh
# Runs inside the nginx (frontend) container via /docker-entrypoint.d/.
# Watches the TLS certificate for changes (certbot renewals land on the shared
# volume) and hot-reloads nginx — zero downtime, no manual intervention.
#
# CERT_WATCH_INTERVAL: seconds between checks (default 3600).

CERT_DIR="/etc/letsencrypt/live"
INTERVAL="${CERT_WATCH_INTERVAL:-3600}"

watch_certs() {
    # Fingerprint every fullchain.pem (path + md5); any change -> reload
    fingerprint() {
        find "$CERT_DIR" -name fullchain.pem -exec md5sum {} \; 2>/dev/null | sort
    }
    last="$(fingerprint)"
    echo "[cert-watcher] watching $CERT_DIR every ${INTERVAL}s"
    while :; do
        sleep "$INTERVAL"
        cur="$(fingerprint)"
        if [ -n "$cur" ] && [ "$cur" != "$last" ]; then
            echo "[cert-watcher] certificate change detected — reloading nginx"
            if nginx -s reload; then
                echo "[cert-watcher] nginx reloaded with new certificate"
                last="$cur"
            else
                echo "[cert-watcher] nginx reload FAILED" >&2
            fi
        fi
    done
}

# Only meaningful when Let's Encrypt certs are mounted (production stack)
if [ -d "$CERT_DIR" ]; then
    watch_certs &
else
    echo "[cert-watcher] $CERT_DIR not present — watcher disabled (dev image)"
fi
