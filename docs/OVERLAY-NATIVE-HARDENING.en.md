# Native overlay preflight parity

[Русский](OVERLAY-NATIVE-HARDENING.md) | English

The original 44-case comparison found35 native mismatches. The native validator
now agrees on an expanded117-case contract: strict keys/types/explicit null,
health budgets, canonical unicast/prefixes, overlaps, tunnel host addresses,
public keys, endpoint/keepalive/role constraints and underlay recursion. An additional24-case ownership suite passes nested list precedence, disabled/
nonoverlapping OSPF, owned list contents, foreign addresses/peers, reserved probe
tables/rules and WG/underlay VRF boundaries. This records the schema-hardening milestone. Subsequent lifecycle/cold-start
checks passed; long candidate acceptance remains in progress. See
[current status](CURRENT-STATUS.en.md).
Malformed configurations are validated without installation. The private report
is `overlay-lab/runtime/overlay-contract-validation.json`.

RouterOS 7.24.5 drops `null` elements when deserializing JSON arrays. Installation
therefore passes **both** parsed configuration and the original JSON to
`sdwanOverlayValidate cfg=$cfg rawJSON=$cfgJSON`. A quote/escape-aware lexical check
rejects actual null tokens without rejecting quoted text such as
`null.example.test`. A parsed object alone cannot recover dropped elements.
The read-only contract tests import only validation functions, leaving the active
controller and actuator functions unchanged.

Implemented schema checks (covered by the expanded contract):

- Enumerate top-level and per-tunnel fields. Require the exact `enabled` boolean,
  required fields, and `enabled=false` without hidden extra settings. Reject
  explicit JSON null for optional values; absence and null are different.
- Match integer/bool ranges, nonempty prefix lists, inner probe train duration
  and stale/recovery budgets. Preserve the existing optional defaults.
- Validate canonical unicast IPv4/router IDs and prefixes, including every
  subprefix of169.254/16; checking one representative host alone is insufficient.
  Reject overlaps within/between sites and links, unusable /30 host addresses,
  and peer prefixes outside the declared remote networks.
- Validate nonzero canonical32-byte public keys, distinct local/peer identities,
  endpoint syntax/port/keepalive and endpoint recursion through all effective
  overlay networks. Hub mode forbids even an empty endpoint option.
- Preserve existing ownership/foreign OSPF checks. Extend later collision tests
  to interface-list include/exclude membership, VRF scope and rollback/reapply.

Keep validation before network mutations and outside the periodic controller
tick. Use bounded prefix comparisons; parse only text already checked to contain
canonical digits, dots and a slash. IPv4 overlap can compare each canonical
network address against the other prefix; containment also compares prefix
lengths. Public-key validation can use RouterOS conversion or a strict44-character
base64 check, including canonical final padding bits and rejection of the zero key.
Do not request actual private keys to test these rules.

Repeat after validator changes:

```text
python3 tests/overlay_contract_acceptance.py --lab-root PRIVATE_ROOT
```

The test uses small batches below the RouterOS file-content limit and the same
nonblocking fabric lock as the other CHR checks. Do not run it during an existing
fabric mutation. Fix the native validator, then require every contract case to agree with
Python before closing this gate. Add cases if the implementation uncovers further
schema or ownership boundaries; a passing subset does not close full acceptance.
