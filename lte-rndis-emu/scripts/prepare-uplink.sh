#!/bin/sh
# Create a tap the emulator can bridge to. Does not start DHCP or assign an address.
set -eu
NAME=${1:-lte0}
if ! command -v ip >/dev/null 2>&1; then
    echo "prepare-uplink: ip(8) is required on the lab host" >&2
    exit 2
fi
if ip link show "$NAME" >/dev/null 2>&1; then
    ip link set "$NAME" up
    echo "uplink $NAME already exists and is up"
    exit 0
fi
ip tuntap add dev "$NAME" mode tap
ip link set "$NAME" up
echo "uplink $NAME is up"
echo "The emulator does not answer DHCP. Put addressing on this tap, or on whatever you bridge it to."
