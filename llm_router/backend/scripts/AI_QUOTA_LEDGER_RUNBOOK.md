# AI quota ledger maintenance

`ai_quota_events` is the immutable source used to recover Redis counters and
audit every admitted platform AI operation. One credit represents one logical
operation admitted by the platform. It remains consumed when the operation
fails; retries or provider failover inside the same operation reuse its
reservation.

After migration `0068_ai_quota_rollups`, run this at least monthly, after the UTC
month has closed:

```bash
python scripts/quota_ledger_maintenance.py --refresh-rollups --warn-gib 20 --warn-rows 50000000
```

Exit code `2` is a capacity alert. Route it to the normal operations alerting
channel and expand PostgreSQL storage before the threshold is reached. The
materialized view provides compact monthly totals; the BRIN time index keeps
closed-period scans bounded as the fact table grows.

Do not manually delete rows. Migration `0066` deliberately rejects UPDATE and
DELETE. A future archive workflow must first define audit retention, export and
checksum a fully closed UTC month, test restore, and only then retire a database
partition. The current UTC month must never be archived or removed because it is
used to seed live Redis monthly counters.
