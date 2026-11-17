import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trendradar.context import AppContext
from trendradar.core import load_config
from trendradar.notification.senders import send_to_feishu
from trendradar.report.archive import publish_report


NOW = datetime(2026, 11, 18, 8, 1, tzinfo=timezone(timedelta(hours=8)))


class FakeS3:
    def __init__(self, fail_key=None):
        self.objects = {"news/2026-11-18.db": b"original database"}
        self.keys = []
        self.fail_key = fail_key

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        if Key == self.fail_key or (self.fail_key == "markdown" and Key.endswith(".md")):
            raise OSError("simulated upload failure")
        assert Bucket == "trendradar-data"
        self.keys.append(Key)
        self.objects[Key] = Body


def publish(tmp_path, client, **kwargs):
    args = dict(report_data={"stats": [], "platform_total": 12}, batches=[],
                generated_at=NOW, report_type="新增热点", mode="incremental",
                output_dir=tmp_path)
    args.update(kwargs)
    return publish_report(SimpleNamespace(s3_client=client, bucket_name="trendradar-data"), **args)


def test_full_batches_hashes_order_and_database_preserved(tmp_path):
    client = FakeS3()
    batches = ["第一批完整内容[来源](https://example.com/1)", "第二批完整内容"]
    manifest = publish(tmp_path, client, batches=batches,
                       report_data={"stats": [{"titles": [{"title": "新闻"}]}]})
    assert client.keys[-2].endswith(".manifest.json")
    assert client.keys[-1] == "reports/latest.json"
    assert json.loads(client.objects[client.keys[-2]]) == manifest
    assert client.objects["news/2026-11-18.db"] == b"original database"
    for descriptor in manifest["files"].values():
        raw = client.objects[descriptor["key"]]
        assert len(raw) == descriptor["bytes"]
        assert hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
    document = json.loads(client.objects[manifest["files"]["json"]["key"]])
    assert document["feishu_batches"] == batches
    markdown = client.objects[manifest["files"]["markdown"]["key"]].decode()
    assert all(batch in markdown for batch in batches)
    assert manifest["delivery_status"] == "not_tracked"


@pytest.mark.parametrize("fail_key", ["markdown", "reports/latest.json"])
def test_failure_keeps_previous_latest_and_local_report(tmp_path, fail_key):
    client = FakeS3(fail_key)
    client.objects["reports/latest.json"] = b"previous complete report"
    with pytest.raises(OSError):
        publish(tmp_path, client)
    assert client.objects["reports/latest.json"] == b"previous complete report"
    assert len(list(tmp_path.rglob("*.md"))) == 1


def test_empty_partial_failed_and_unique_runs(tmp_path):
    client = FakeS3()
    first = publish(tmp_path, client)
    second = publish(tmp_path, client)
    assert first["report_id"] != second["report_id"]
    assert second["status"] == "no_new_matches"
    assert "本期无新增匹配新闻" in client.objects[second["files"]["markdown"]["key"]].decode()
    partial = publish(tmp_path, client, report_data={"stats": [], "platform_total": 2, "failed_ids": ["a"]})
    assert partial["status"] == "no_new_matches"
    assert partial["failed_source_ids"] == ["a"]
    failed = publish(tmp_path, client, report_data={"stats": [], "platform_total": 2, "failed_ids": ["a", "b"]})
    assert failed["status"] == "collection_failed"


def test_archive_matches_every_actual_feishu_batch(monkeypatch):
    cfg = load_config()
    cfg["FEISHU_BATCH_SIZE"] = 1800  # force multiple batches
    ctx = AppContext(cfg)
    ctx.get_time = lambda: NOW
    dispatcher = ctx.create_notification_dispatcher()
    titles = [dict(title=f"完整新闻 {i} " + "内容" * 60, source_name="测试来源", time_display="08:00",
                   count=1, ranks=[1], rank_threshold=3, url=f"https://example.com/{i}", mobile_url="", is_new=True)
              for i in range(18)]
    data = {"stats": [{"word": "测试", "count": len(titles), "titles": titles}],
            "new_titles": [], "failed_ids": [], "hotlist_total": 18, "platform_total": 1}
    archived = dispatcher.prepare_feishu_archive(data, "新增热点", mode="incremental")
    sent = []

    def post(url, **kwargs):
        sent.append(kwargs["json"]["content"]["text"])
        return SimpleNamespace(status_code=200, json=lambda: {"code": 0})

    monkeypatch.setattr("trendradar.notification.senders.requests.post", post)
    assert send_to_feishu("https://www.feishu.cn/test", data, "新增热点", mode="incremental",
                          batch_size=1800, batch_interval=0, split_content_func=ctx.split_content)
    assert len(archived) > 1
    assert archived == sent
    assert all(f"https://example.com/{i}" in "".join(archived) for i in range(18))


def test_pipeline_archives_even_with_notifications_disabled(tmp_path, monkeypatch):
    from trendradar.__main__ import NewsAnalyzer

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPORT_ARCHIVE_ENABLED", "true")
    client = FakeS3()
    analyzer = object.__new__(NewsAnalyzer)
    schedule = SimpleNamespace(collect=True, report_mode="incremental", frequency_file=None,
                               filter_method="keyword", interests_file=None)
    dispatcher = Mock()
    dispatcher.prepare_feishu_archive.return_value = []
    ctx = Mock()
    ctx.config = {"ENABLE_NOTIFICATION": False, "SHOW_VERSION_UPDATE": False}
    ctx.platform_ids = ["a"]
    ctx.create_scheduler.return_value.resolve.return_value = schedule
    ctx.load_frequency_words.return_value = ([], [], [])
    ctx.prepare_report.return_value = {"stats": [], "failed_ids": []}
    ctx.get_time.return_value = NOW
    ctx.create_notification_dispatcher.return_value = dispatcher
    analyzer.ctx = ctx
    analyzer.report_mode = "incremental"
    analyzer.frequency_file = None
    analyzer.update_info = None
    analyzer.is_docker_container = True
    analyzer.storage_manager = SimpleNamespace(get_backend=lambda: SimpleNamespace(s3_client=client, bucket_name="trendradar-data"))
    for attr in ["_rss_source_total", "_rss_source_failed", "_rss_total_count", "_rss_matched_count", "_hotlist_total_count"]:
        setattr(analyzer, attr, 0)
    analyzer._prepare_current_title_info = Mock(return_value={})
    analyzer._prepare_standalone_data = Mock(return_value=None)
    analyzer._run_analysis_pipeline = Mock(return_value=([], None, None, None, None, None))
    analyzer._has_notification_configured = Mock(return_value=False)
    analyzer._should_open_browser = Mock(return_value=False)
    analyzer._execute_mode_strategy(analyzer._get_mode_strategy(), {}, {}, [])
    assert json.loads(client.objects["reports/latest.json"])["status"] == "no_new_matches"
    dispatcher.dispatch_all.assert_not_called()
