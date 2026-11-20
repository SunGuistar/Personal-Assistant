"""存储统计使用独立临时目录，不初始化真实数据库或向量客户端。"""
from pathlib import Path

from app.adapters.storage_inventory import SizeScanner
from app.config import Settings
from app.services.storage_inventory import storage_overview


def put(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_overview_sizes_sidecars_retention_and_no_writes(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    put(settings.data_dir / "hub.db", 100)
    put(settings.data_dir / "hub.db-wal", 20)
    put(settings.data_dir / "hub.db-shm", 5)
    put(settings.data_dir / "morning_report.db", 40)
    put(settings.data_dir / "morning_report.db.checkpoint", 30)
    put(settings.data_dir / "hub.db.pre-test.bak", 10)
    put(settings.data_dir / "hub.before-test.db", 15)
    put(settings.reading_notes_dir / "note.txt", 8)
    put(tmp_path / "GetWechatInfo/VectorStore/chroma_db/chroma.sqlite3", 12)
    put(tmp_path / "Output/report.html", 6)
    put(settings.logs_path / "hub.log", 4)
    # 不应扫描密钥或任意数据目录文件。
    put(settings.data_dir / ".env", 999)
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    result = storage_overview(settings, root=tmp_path, normalized_path=tmp_path / "normalized.db", cache_hours=24)
    items = {i["id"]: i for i in result["items"]}
    assert items["hub"]["size_bytes"] == 125
    assert items["migration_copies"]["size_bytes"] == 25
    assert items["chroma"]["size_bytes"] == 12
    assert items["qdrant"]["size_bytes"] is None
    assert "24 小时" in items["morning"]["description"]
    assert result["total_bytes"] == 250
    after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_size_scanner_deduplicates_and_limits_work(tmp_path):
    put(tmp_path / "a", 10)
    scanner = SizeScanner()
    assert scanner.measure([tmp_path / "a", tmp_path / "a"])["size_bytes"] == 10
    assert scanner.measure([tmp_path / "a"])["size_bytes"] == 0
    assert SizeScanner(max_entries=0).measure([tmp_path])["size_bytes"] is None


def test_unreadable_files_are_unknown_not_zero(tmp_path, monkeypatch):
    path = tmp_path / "unreadable"
    original = Path.stat

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("isolated test")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    result = SizeScanner().measure([path])
    assert result["size_bytes"] is None
    assert "不完整" in result["note"]


def test_missing_paths_do_not_create_directories(tmp_path):
    result = storage_overview(Settings(data_dir=tmp_path / "missing"), root=tmp_path,
                              normalized_path=tmp_path / "normalized.db")
    assert result["total_bytes"] == 0
    assert not list(tmp_path.iterdir())


def test_api_only_exposes_readonly_inventory(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.storage import router
    from app.api.deps import get_settings
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: Settings(data_dir=tmp_path)
    # 替换 Service 防止接口测试访问工作区存储。
    from unittest.mock import patch
    with patch("app.api.storage.storage_overview", return_value={"checked_at": "now", "total_bytes": 0, "items": []}):
        with TestClient(app) as client:
            assert client.get("/api/storage/overview").json()["total_bytes"] == 0
            assert client.post("/api/storage/overview").status_code == 405
