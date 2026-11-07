# Drafts with existing mangle rules

[Русский](MIGRATION.md) | English

The wizard can generate a configuration draft when the inspected snapshot has
active third-party `mark-connection`, `mark-routing` or `route` rules. Generation
does not change MikroTik. Programmatic `generate()` remains strict by default;
the wizard explicitly selects draft mode with `allow_foreign_mangle=True`.

Step 3 shows a draft indicator and an old-rule migration tab. It lists IDs,
chains, actions, marks, selectors and comments of conflicting rules. MSS, DSCP
and `mark-packet` rules alone do not require disabling. Disabled rules and owned
`sdwan:v1:` objects are excluded; custom chains are inspected too.

Saving JSON creates `<name>.json.migration.json` and `<name>.json.migration.txt`
sidecars. Reopening the JSON restores its warning. RouterOS export also creates
`MIGRATION-REVIEW.txt` and `MIGRATION-REVIEW.json`. These private local reports can
contain routing details and are excluded from Git.

## Before applying

1. Retain an original export/backup and a recovery access path.
2. Understand each listed rule. Move required client/destination selectors into
   SD-WAN policies. Review VPN control traffic and internal/branch exemptions for OSPF.
3. Disable only conflicting old marks that the new configuration replaces. The
   current version requires these conflicts to be disabled; it does not merge
   arbitrary marking systems. Do not disable all mangle rules in bulk.
4. Read the device again and regenerate. Review the change plan and routes before
   installation.

Installation stays blocked while the draft has known conflicts. API preflight
reads current rules before transferring the package; the native installer checks
again on manual import. Deleting a sidecar, reopening JSON or exporting `.rsc`
files does not bypass these guards. Valid JSON alone does not establish device
readiness.

With the default `policy-rules` order, RouterOS checks the mangle-marked table
before ordinary routing rules. If that table resolves the destination, new rules
alone do not replace the old classification. Adding rules on top of an existing
scheme is not sufficient migration design. See
[RouterOS Routing Decision](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/routing-decision/).
