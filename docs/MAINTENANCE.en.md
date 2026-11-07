# API, space and backup retention

[Русский](MAINTENANCE.md) | English

Single-file lookup uses an exact-name API query, including correct precedence
of `flash/` over the legacy root. Journal polling does not repeatedly transfer
the whole directory. Uploading existing text compares contents first: identical
content avoids `/file set`. New files are created empty and filled with a separate
`set` so their contents are not copied into the log.

Before deployment file changes, preflight requires an internal-space reserve of
1 MiB plus twice the payload size. This is a lower bound, not a prediction of
encrypted-backup size; bootstrap still verifies backup creation before changing
the network. External storage availability and space for the root directory are
checked separately during container preparation.

## Inspect and prune old archives

CLI defaults to a preview. Supply the normal connection options, credentials and
expected identity for your own isolated lab device:

```sh
python3 sdwan.py --url api://127.0.0.1:18728 prune-backups --keep 3
python3 sdwan.py --url api://127.0.0.1:18728 prune-backups --keep 3 --execute
```

The most recent N confirmed groups are retained using journal/metadata time.
The current group is always protected, together with transitive manifest
dependencies and groups without a reliable date. Ties at the cutoff preserve
all tied groups. `keep` accepts 1–20. Active configuration, baseline, secret
mounts and user files are never deletion candidates.

Only strictly named `sdwan-before-TOKEN.backup`, `sdwan-prev-TOKEN-INDEX`,
`sdwan-infra-prev-TOKEN-INDEX` and `sdwan-txn-TOKEN.json` files belonging to a
verified completed journal for the same device can be deleted. TOKEN has 24 hex
characters. Unknown/orphan files without a confirming journal remain. A group's
journal is removed last so interrupted cleanup can be resumed.

Pending/recovery-failed transactions, ambiguous journals, identity/token mismatch
or differing flash/root copies block automatic deletion. Before every deletion,
the current transaction and exact file ID are checked again. An error stops
remaining cleanup; it does not start reinstallation or rollback.

## Automatic cleanup after confirmed deployment

Enable it explicitly in the GUI file/local-network tab or the complete JSON:

```json
{"maintenance": {"backup_keep": 3}}
```

This is a fragment of an existing configuration. Older JSON without `maintenance`
keeps its previous behavior: no automatic deletion. The deployment plan shows
the policy and current cleanup estimate. Candidates are recomputed after a new
committed package, protecting the new transaction. If cleanup is blocked, the
deployment remains committed and the reason is reported separately.

The configurator/CLI performs maintenance once after ACK. There is no periodic
job or flash counter write. If the client closes after ACK, cleanup can be run
separately; SD-WAN operation does not depend on it. Recovery keys on the operator's
computer are not deleted automatically.

Implemented RAM statistics/web are described in [STATISTICS.md](STATISTICS.en.md).
The original design remains in [STATISTICS-DESIGN.md](STATISTICS-DESIGN.en.md).
