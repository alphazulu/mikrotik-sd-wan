# lte-rndis-emu

Userspace RNDIS device for a MikroTik CHR lab. QEMU attaches it with `usb-redir`. Ethernet frames are bridged to the interface given as `--uplink`. There is no DHCP server in this process.

The agent-facing contract is [USAGE.md](USAGE.md).

```bash
python3 -m lte_rndis_emu probe
python3 -m unittest discover -s tests -v
python3 -m lte_rndis_emu serve --uplink lte0
```
