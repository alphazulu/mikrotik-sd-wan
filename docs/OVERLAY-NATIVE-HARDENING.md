# Native overlay preflight parity: open development gate

The API/GUI Python model rejects malformed overlay settings. A new **44-case**
CHR comparison with `sdwanOverlayValidate` found **35 native mismatches**. This
gate is open; the current branch must not be described as fully accepted or
released. Cases execute read-only preflight against existing lab identities,
without applying malformed network settings. The private report is
`overlay-lab/runtime/overlay-contract-validation.json`.

Required native work before the final soak:

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

Repeat after implementation:

```text
python tests/overlay_contract_acceptance.py --lab-root PRIVATE_ROOT
```

The test uses small batches below the RouterOS file-content limit and the same
nonblocking fabric lock as the other CHR checks. Do not run it during an existing
fabric mutation. Fix the native validator, then require all44cases to agree with
Python before closing this gate. Add cases if the implementation uncovers further
schema or ownership boundaries; a passing subset does not close full acceptance.
