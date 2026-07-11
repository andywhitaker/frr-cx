#!/bin/sh
# Entrypoint for Nokia EDA CX SimNodes running FRR.
# 1) Wait for CX datapath interfaces
# 2) Enable IPv6 on datapath interfaces
# 3) Fetch FRR configs from the EDA artifact server
# 4) Hand off to the stock FRR docker-start

set -eu

log() {
    echo "[frr-cx] $*"
}

log "Waiting for datapath interfaces to be injected by CX..."
max_retries="${DATAPATH_WAIT_SECONDS:-30}"
counter=0
while true; do
    # eth0 is management; CX injects eth1, eth2, ... (and may create *-cx helpers).
    if ls /sys/class/net 2>/dev/null | grep -E '^eth[1-9][0-9]*$' >/dev/null 2>&1; then
        break
    fi
    counter=$((counter + 1))
    if [ "$counter" -ge "$max_retries" ]; then
        log "Timeout waiting for datapath interfaces. Proceeding anyway..."
        break
    fi
    sleep 1
done

# Allow any remaining interfaces a moment to appear.
sleep 1

log "Enabling IPv6 on datapath interfaces..."
for intf in $(ls /sys/class/net 2>/dev/null | grep -E '^eth[1-9][0-9]*$' || true); do
    # Skip CX helper interfaces if present.
    case "$intf" in
        *-cx) continue ;;
    esac
    log "  configuring $intf"
    sysctl -w "net.ipv6.conf.${intf}.disable_ipv6=0" >/dev/null
    sysctl -w "net.ipv6.conf.${intf}.autoconf=1" >/dev/null || true
    ip link set "$intf" down || true
    ip link set "$intf" up || true
done

log "Fetching FRR configuration from EDA artifact server..."
python3 /opt/frr-cx/get_configs.py

log "Starting FRR..."
exec /usr/lib/frr/docker-start
