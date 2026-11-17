"""Private, immutable full push reports alongside the existing news databases."""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def archive_enabled():
    return os.environ.get("REPORT_ARCHIVE_ENABLED", "").lower() in {"1", "true", "yes"}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def publish_report(backend, *, report_data, batches, generated_at: datetime,
                   report_type, mode, rss_items=None, rss_new_items=None,
                   standalone_data=None, output_dir="output/reports"):
    """Upload content first, then publish latest.json as the completion marker.

    No database keys are written. A local copy survives an R2 outage; failures
    propagate to the caller and never advance the R2 completion marker.
    """
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("Report time must include a timezone")
    if not getattr(backend, "s3_client", None) or not getattr(backend, "bucket_name", None):
        raise RuntimeError("Full report archival requires a remote S3 backend")

    report_id = generated_at.strftime("%Y-%m-%d/%H-%M-%S-%f-") + uuid4().hex[:8]
    base_key = f"reports/{report_id}"
    news_count = sum(len(s.get("titles", [])) for s in report_data.get("stats", []))
    rss_count = sum(len(s.get("titles", [])) for s in (rss_items or []))
    failed_ids = report_data.get("failed_ids", [])
    source_total = report_data.get("platform_total", 0)
    status = "ready" if news_count or rss_count else "no_new_matches"
    if source_total and len(failed_ids) >= source_total:
        status = "collection_failed"
    metadata = {
        "schema_version": 1,
        "report_id": report_id,
        "generated_at": generated_at.isoformat(),
        "mode": mode,
        "report_type": report_type,
        "status": status,
        "news_count": news_count,
        "rss_count": rss_count,
        "collected_count": report_data.get("hotlist_total", 0),
        "source_total": source_total,
        "failed_source_ids": failed_ids,
        "delivery_status": "not_tracked",
    }
    # Batches are the complete Feishu body, including all split messages.
    body = "\n\n---\n\n".join(batches)
    if status != "ready":
        message = "本期采集失败，不能据此判断没有新闻。" if status == "collection_failed" else "本期无新增匹配新闻。"
        body = message + "\n\n" + body
    markdown = (f"# TrendRadar {report_type}\n\n"
                f"生成时间：{metadata['generated_at']}\n\n"
                f"报告 ID：{report_id}\n\n{body}\n").encode("utf-8")
    document = {
        **metadata,
        "report_data": report_data,
        "rss_items": rss_items or [],
        "rss_new_items": rss_new_items or [],
        "standalone_data": standalone_data,
        "feishu_batches": batches,
    }
    json_body = _json_bytes(document)
    files = {
        "json": {"key": base_key + ".json", "sha256": hashlib.sha256(json_body).hexdigest(), "bytes": len(json_body)},
        "markdown": {"key": base_key + ".md", "sha256": hashlib.sha256(markdown).hexdigest(), "bytes": len(markdown)},
    }
    manifest = {**metadata, "files": files}
    manifest_body = _json_bytes(manifest)
    local_base = Path(output_dir) / report_id
    local_base.parent.mkdir(parents=True, exist_ok=True)
    local_base.with_suffix(".json").write_bytes(json_body)
    local_base.with_suffix(".md").write_bytes(markdown)
    local_base.with_suffix(".manifest.json").write_bytes(manifest_body)

    for key, data, content_type in [
        (files["json"]["key"], json_body, "application/json; charset=utf-8"),
        (files["markdown"]["key"], markdown, "text/markdown; charset=utf-8"),
        # Per-report marker also lets readers recover missed periods safely.
        (base_key + ".manifest.json", manifest_body, "application/json; charset=utf-8"),
        ("reports/latest.json", manifest_body, "application/json; charset=utf-8"),
    ]:
        backend.s3_client.put_object(
            Bucket=backend.bucket_name, Key=key, Body=data,
            ContentType=content_type, CacheControl="no-store",
        )
    return manifest
