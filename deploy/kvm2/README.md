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
