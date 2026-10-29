# Configuring branches with the GUI

[Русский](OVERLAY-GUI.md) | English

Optional development-version feature. Targeted native/container checks passed;
long candidate acceptance continues. MikroTik itself makes routing decisions;
GUI configures through API.

Branches both behind CGNAT need a reachable public hub. Each site establishes
outbound WireGuard through each WAN; hub responds. Network owners supply actual
public/branch addressing. Tests use CHR only.

1. Inspect the target router and configure physical WANs with the normal wizard.
   Open branch WG/OSPF on step 3.
2. Explicitly enable overlay. Set role, unique OSPF Router ID, exact local prefixes
   to advertise and all remote networks. Hub can have an empty local list.
   Existing OSPF is not migrated.
3. Add paths: unique name/local UDP port, physical WAN, inside `/30` or `/31`
   address pair, peer networks and OSPF cost. Sites need reachable hub endpoint/
   port and keepalive; hub removes those three options from JSON because it responds.
4. Prepare local keys on MikroTik. Path names/ports and global MTU suffice. This
   separate action creates disabled interfaces with RouterOS-generated keys only.
   Protected deployment adds addresses/peers/routes/firewall later. Existing keys
   are retained; foreign collisions and pending transactions block preparation.
5. Export public keys as JSON. On the other router, select a path, import peer key
   from file and choose the corresponding remote interface. Exchange in both
   directions. Do not import router exports/private keys; format accepts public
   fields only.
6. Set inner SLA, MTU and optional TCP MSS. Generate/save per-node JSON, review
   the common plan and deploy safely. Repeat on other nodes; no distributed atomic
   multi-router installation is provided.

End names can differ; select peers explicitly. Do not advertise management
networks as client networks. Each link has separate addresses/keys/ports. Branch
networks must not overlap WANs or links. If all paths fail, exact remote prefixes
close with blackhole routes. Internet/VPN-egress policies remain in the same
SD-WAN; private branch prefixes bypass Internet classification.

Public exchange files are limited to 32 KiB/16 entries, without passwords, private
keys, certificates or API credentials. Preparation/installation are explicit;
periodic operation does not persist state to flash. Disabling the project option
sets `overlay.enabled=false`; network removal happens through protected deployment,
not merely opening a dialog.

This milestone used five offline and four live Windows/Tk scenarios plus two
CHR key-preparation/public-readback checks. Diagnostics shows SLA admission and
actual OSPF Full neighbors separately, marking both stale when the snapshot ages.
Subsequent native lifecycle/cold-start and container results are in
[current status](CURRENT-STATUS.en.md). See [topology/limits](OVERLAY-DESIGN.en.md)
and [network plan](NEXT-NETWORK-PLAN.en.md).
