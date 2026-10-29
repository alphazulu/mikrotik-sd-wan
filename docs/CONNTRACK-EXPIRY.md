# Conntrack expiry during cleanup / Истечение записей connection tracking

An isolated RouterOS 7.24.5 x86 L6 fixture reproduced a deployment failure after
short TCP/UDP workloads and 7,000 CPS connections. The protected deployment
reported `no such item (4)` and automatically rolled back. A no-load fixture had
passed, so that earlier success did not cover this condition.

Private stage instrumentation narrowed the failure to the policy purge call.
A separate error handler around its initial
`/ip/firewall/connection/find where connection-mark=$mark` captured the same
error before any removal. An earlier last-stage label pointed at mangle; it was
not sufficient evidence that the mangle operation failed. No production router
was changed during diagnosis.

На стенде ошибка возникала уже при получении списка записей, до `remove`.
Защита только вокруг удаления была недостаточна. Кандидат повторяет получение
списка ограниченное число раз, сохраняя точные фильтры и передачу остальных ошибок.

## Candidate behaviour

`sdwanConntrackFind`, loaded from `sdwan-links.rsc`, executes an explicit query
callback. It passes named mark/socket/endpoint selectors rather than relying on
the caller's variable scope. Only an error beginning with `no such item` is
retried: at most five attempts, with 10 ms between attempts. A fifth failure or
any other error is propagated. An empty successful result returns immediately.

Controller, dynamic-link, VPN transport, overlay transport, dataplane retirement
and rollback cleanup use this helper. Their existing mark/tuple/local-address
filters are preserved. Removal still tolerates an already vanished ID; permission
and other failures propagate without another racy full-table existence query.
This does not disable connection tracking or flush unrelated connections.

The generic callback helper is used only by router-local scripts. It adds no
external controller, API endpoint, scheduler or periodic flash writes.

The [RouterOS scripting reference](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting)
documents internal-ID results from `find` and `:onerror` handling. The race above
is an observed lab result; the documentation does not promise an atomic conntrack
snapshot.

## Validation boundary

`tests/conntrack_retry_acceptance.rsc` exercises actual RouterOS semantics with
synthetic callbacks: selectors/results survive retries, two transient failures
recover on the third attempt, empty results remain empty, permission errors are
not retried and persistent transient errors stop after five attempts. Run it
after importing `sdwan-links.rsc` in the same script environment. The dedicated
fixture ran it through a self-disabling Scheduler, matching controller execution.

These five checks pass on the isolated x86 L6 fixture. A short loaded RSC startup,
six workloads, WAN failover/failback and pinned-flow preservation also pass.
The complete native/container/web cycle and broader transport regressions remain
pending. A passing original 48-hour soak
would cover its frozen native source only; it cannot approve this native change.
The comparison gate checks native file hashes for that reason. Container Rust/JS
source and its exact-source coverage are unchanged by this fix.
