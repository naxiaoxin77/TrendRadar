# KVM 2 deployment

This deployment builds the repository source on a pinned TrendRadar base image.
It runs one crawler, using the existing private R2 bucket and Feishu credentials
from `/etc/trendradar/runtime.env` (root-only, outside this repository).

The schedule is 00:00, 08:00 and 16:00 Asia/Singapore (`0 */8 * * *`).
The existing incremental report mode is retained: no empty message is sent when
there is no newly matched news. GitHub Actions crawling stays disabled.

Deployment root: `/opt/trendradar/repo`; writable output: `/opt/trendradar/output`.
The service publishes no host ports.

Required environment-file keys:

- S3_ENDPOINT_URL
- S3_BUCKET_NAME
- S3_ACCESS_KEY_ID
- S3_SECRET_ACCESS_KEY
- S3_REGION=auto
- FEISHU_WEBHOOK_URL

From the repository root:

```sh
SOURCE_REVISION=$(git rev-parse HEAD) docker compose -f deploy/kvm2/compose.yml build
docker compose -f deploy/kvm2/compose.yml up -d
docker compose -f deploy/kvm2/compose.yml ps
docker compose -f deploy/kvm2/compose.yml logs --tail 100
```

The deployment explicitly passes `STORAGE_BACKEND=remote` into the container.
Secrets must not be added to the tracked `docker/.env` file.

## Full push report archive

`REPORT_ARCHIVE_ENABLED=true` archives every completed analysis, before deciding
whether to send notifications. Feishu failures and periods without new matches
do not suppress archival. Existing `news/YYYY-MM-DD.db` storage and retention
are unchanged; report archive objects have no automatic deletion policy here.

The existing private bucket receives:

- `reports/YYYY-MM-DD/HH-MM-SS-microseconds-id.json`: report data, metadata,
  and **all** Feishu message batches from the shared Feishu renderer.
- The matching `.md`: complete readable push body with generation time.
- The matching `.manifest.json`: completed content keys, byte counts and SHA-256.
- `reports/latest.json`: latest completed manifest, published after both bodies.

There is also a durable copy under `/opt/trendradar/output/reports`. Upload errors
leave the previous latest pointer intact and log an archival failure; local copies
can be re-uploaded manually. Notification delivery status is not claimed by the
archive (`delivery_status=not_tracked`). Currently AI analysis and translation
remain disabled; Codex reads this archive and writes the summary separately.

Readers should verify the completion manifest and content hashes, distinguish
`ready`, `no_new_matches` and `collection_failed`, warn about partial failed
sources, and track processed report IDs. They must not treat an old pointer as
new news. Per-report manifests support catching up after a missed reader run.
This stores titles, source links, ranking and the existing processed report;
it does not fetch the full text of every linked article.

The requested Codex reader schedule is 00:10, 08:10 and 16:10 Asia/Singapore,
ten minutes after the crawler. Codex scheduling is managed in the desktop app,
not by another server cron or a public R2 endpoint.
