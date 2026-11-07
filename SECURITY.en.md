# Configuration and credentials

[Русский](SECURITY.md) | English

The repository contains source and synthetic lab examples. Real device exports,
their analyses, saved discovery snapshots, passwords, keys, backups, logs, VM disks
and screenshots are not published.

Keep private files in `runtime/` or local `config/local*.json` files. `.gitignore`
excludes these paths, root RSC exports, `config/discovered-*.json`, credentials,
keys and `.env`. Ignore rules do not protect files already tracked by Git. Before
each push, review `git diff --cached` and run `python3 tools/audit_public_tree.py`.

CLI credentials use a separate JSON file; the router password is not an SD-WAN
configuration field. Recovery journals and encrypted-backup keys contain secrets.
Restrict file access, including Windows ACLs. Do not attach `runtime/` or a real
device export to a public issue. Use a minimal synthetic configuration to reproduce
a problem.

## API and container

Plain RouterOS API does not encrypt traffic. For remote management use API TLS
with hostname/CA validation or a trusted protected transport. The configurator
does not require publishing router management services on the Internet.

The container has a dedicated user restricted to its veth IP and an isolated `/30`
network. RouterOS API permissions are broad; they do not provide per-file or
per-command ACLs. Required `read,write,policy,test,sensitive,api` permissions are
explicit, and other permissions are disabled. Read-only mounts supply the password
and JSON; neither is embedded in the scratch image. Preparation rules restrict
outbound and forwarded container traffic.

## Deployment and recovery

Protected installation needs backup/reboot privileges. The RouterOS watchdog
checks a fresh API ACK and restores the binary backup after a failure. Restore
reboots the device and also undoes unrelated changes made after that snapshot;
avoid concurrent editing during deployment. Disk/power failures and a watchdog
manually disabled by an operator are outside that recovery guarantee.

See [deployment](docs/DEPLOYMENT.en.md), [container setup](docs/CONTAINER.en.md)
and [OSPF/VPN compatibility](docs/OSPF.en.md).
