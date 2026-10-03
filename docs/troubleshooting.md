# Troubleshooting

Start with the freshness view:

```sql
SELECT * FROM v_feed_freshness;                       -- who is stale / failing
SELECT * FROM etl_run_log ORDER BY run_id DESC LIMIT 10;  -- error_message per failed run
```

| Symptom | Likely cause | Fix |
|---|---|---|
| `401` / `403` in logs | Expired or wrong API key/token | Rotate the key, update env / repo secret. Not retried by design. |
| `403` from localhost:5000 on macOS | AirPlay Receiver owns port 5000 | The mock API uses 5050. |
| Run `FAILED`, error `503` / timeout | Partner outage | Retries (4x, backoff) already happened. Next scheduled run picks up automatically via the watermark. |
| `unmapped status ... -> UNKNOWN` warning | Partner added a new status | Add it to the mapping dict in `etl/partners.py` and re-run with `--full`. |
| `skipping malformed record` warning | Partner changed a field name / null | Check the logged raw record, update the normalizer. |
| Data looks stale but runs succeed | Watermark ahead of reality | `python -m etl.run --full --partner <code>` (safe, idempotent). |
| Actions refresh didn't run on time | GitHub delays cron under load; inactive repos get schedules disabled after 60 days | Trigger manually (workflow_dispatch) / re-enable. |
