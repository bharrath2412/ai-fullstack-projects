# Operations runbook

This is the on-call runbook for the DocMind production platform. It covers incident severity,
escalation, routine maintenance and the two procedures that get asked about most often: key
rotation and database failover.

## Severity definitions

| Severity | Definition | First response |
| --- | --- | --- |
| Sev-1 | Full outage, data loss, or a security breach | page on-call immediately, 5 min ack |
| Sev-2 | Major feature unavailable or >10% of requests failing | page on-call, 15 min ack |
| Sev-3 | Degraded performance, single-customer impact | ticket, next business day |
| Sev-4 | Cosmetic or documentation issue | backlog |

## On-call escalation path

1. **Primary on-call engineer** — paged by the alerting system, acknowledges within 5 minutes.
2. **Secondary on-call** — paged automatically if the primary does not acknowledge in 10 minutes.
3. **Engineering manager** — notified for every Sev-1 and for any Sev-2 open longer than 30 minutes.
4. **Incident commander** — for a Sev-1, the secondary on-call becomes incident commander and runs
   the incident channel (`#inc-<date>-<slug>`); they coordinate rather than debug.
5. **Executive escalation** — VP Engineering and the customer success lead are pulled in for a
   Sev-1 exceeding 60 minutes or any confirmed data loss.

Every Sev-1 gets a written post-incident review within 48 hours, blameless, with action items
that have owners and dates.

## Rotating a leaked API key

1. Open the admin console → **Workspace → API keys**.
2. Create a replacement key with the same scopes; copy it into the secrets manager.
3. Deploy the new key to services (the config is hot-reloaded; no restart required).
4. Verify traffic succeeds with the new key: `GET /v1/whoami` should return the workspace id.
5. Revoke the leaked key. Revocation is immediate and the key is rejected by every edge within
   5 seconds.
6. Search the audit log for requests made with the old key in the last 30 days and open a
   security review if any originated from an unknown IP or ASN.

Never rotate by editing the key in place: create-then-revoke avoids downtime and gives you a
rollback path.

## Database failover

Production runs a primary with two synchronous replicas in different availability zones.

- **Automatic failover** is triggered when the primary misses three consecutive health checks
  (about 45 seconds). The orchestrator promotes the replica with the lowest replication lag.
- The write path returns HTTP 503 `database_unavailable` while promotion completes; typical
  total failover time is 40–90 seconds.
- Clients must retry 503 responses with backoff. Reads continue to be served from the surviving
  replica, so search stays available during the failover window.
- After failover, check `pg_stat_replication` for the new topology and re-attach the demoted node
  as a replica once it is reachable. Alert if replication lag exceeds 30 seconds for more than
  two minutes.

## Routine maintenance

- **Deploys** happen continuously behind feature flags; only migrations require a change window.
- **Migrations** must be backwards compatible for one release (expand/contract pattern).
- **Index rebuilds** (re-embedding the corpus) run as a background job and swap the index
  atomically; expect roughly 90 seconds per 10,000 chunks with the hashing embedder and several
  minutes with a hosted embedding model.
- **Backups** run hourly (incremental) and nightly (full); a restore drill happens monthly and
  the result is recorded in the reliability log.

## Dashboards and alerts

- `Latency / p95 answer time` — alert if p95 > 4s for 10 minutes.
- `Retrieval hit-rate` — weekly regression job; alert if hit@5 drops below 0.70.
- `Queue depth` — ingestion queue; alert if growth outpaces drain for 15 minutes.
- `Error budget` — burn rate alert at 2x and 10x the sustainable rate.
