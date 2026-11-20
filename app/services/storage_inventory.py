"""存储台账和保留规则；只统计元数据，不调用业务查询或清理入口。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..adapters.storage_inventory import SizeScanner, sqlite_files
from ..config import ROOT_DIR, Settings


def storage_overview(settings: Settings, *, root: Path = ROOT_DIR, morning_filename: str = "morning_report.db",
                     cache_hours: int = 12, normalized_path: Path | None = None) -> dict:
    normalized = normalized_path or Path(os.environ.get("WECHAT_AGENT_DB") or root / "GetWechatInfo/DataInfo/chat_snapshot_normalized.sqlite3")
    data = settings.data_dir
    specs = [
        ("hub", "主业务库", "sql", "SQLite", data / "hub.db", "按数据分类保留", "计划、任务、备忘、重要信息、阅读、经验、GitHub 和对话等；业务记录由用户主动管理，清理审计等辅助记录未统一定义期限。", True),
        ("wechat_snapshot", "微信快照库", "sql", "SQLite", root / "GetWechatInfo/DataInfo/chat_snapshot.sqlite3", "7 天后人工审核", "超过保留窗口只进入清理候选，不自动删除；保护日期永久保留。", True),
        ("wechat_normalized", "微信归一化库", "sql", "SQLite", normalized, "7 天后人工审核", "与快照库采用同一审核规则，保护日期永久保留。", True),
        ("chroma", "微信向量库", "vector", "Chroma", root / "GetWechatInfo/VectorStore/chroma_db", "随消息审核清理", "含保护消息、混合日期或归属不明的分块可能保留；统计整个向量目录，不初始化 Chroma。", False),
        ("morning", "晨报数据库", "sql", "SQLite", data / morning_filename, "按数据分类保留", f"报告、新闻、运行记录和证据快照尚无统一删除期限；阶段缓存有效期由配置决定（当前 {cache_hours} 小时），过期不等于立即释放文件空间。", True),
        ("checkpoint", "晨报工作流检查点", "sql", "SQLite", data / (morning_filename + ".checkpoint"), "未定义", "保存工作流中间状态；当前没有明确的定期清理期限。", True),
        ("reading", "阅读附件", "file", "文件", settings.reading_notes_dir, "随关联笔记保留", "附件随笔记管理，无自动到期清理。", False),
        ("reports", "历史总结与问答", "file", "文件", root / "Output", "长期保留", "历史报告兼容保留，未经用户确认不清理。", False),
        ("logs", "运行日志", "file", "文件", settings.logs_path, "按日志轮转规则", "主日志按天轮转，最多保留 7 个轮转文件；其他日志不保证使用相同规则。", False),
    ]
    items = []
    scanner = SizeScanner()
    for sid, name, kind, engine, path, retention, description, sqlite in specs:
        result = scanner.measure(sqlite_files(path) if sqlite else [path])
        items.append(dict(id=sid, name=name, storage_type=kind, engine=engine, path=str(path.absolute()),
                          retention=retention, description=description,
                          size_basis="主文件及已有 WAL、SHM、journal 文件的逻辑字节数" if sqlite else "目录内普通文件的逻辑字节数，不跟随符号链接或目录联接",
                          **result))
    # 只枚举数据目录顶层的已有迁移副本，不递归扫描用户目录。
    result = scanner.migration_copies(data)
    items.append(dict(id="migration_copies", name="已有迁移副本", storage_type="file", engine="数据库文件副本", path=str(data.absolute()),
                      retention="未定义", description="仅统计已有的 *.bak 和 hub.before-*.db，不创建备份或恢复功能。",
                      size_basis="数据目录顶层匹配文件的逻辑字节数", **result))
    items.append(dict(id="qdrant", name="晨报向量库", storage_type="vector", engine="Qdrant", path="http://127.0.0.1:6333",
                      retention="历史保留／未定义", description="morning_tech_news / morning_reports；当前晨报生成不再更新此索引。",
                      size_basis="服务端磁盘占用无法从本机目录可靠获得", size_bytes=None, file_count=None,
                      note="未配置服务端存储目录，大小未知，不计入总占用。"))
    return {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "total_bytes": sum(i["size_bytes"] for i in items if i["size_bytes"] is not None), "items": items}
