"""有界文件元数据扫描；不打开数据库、初始化客户端或跟随目录链接。"""
from __future__ import annotations

import os
import time
from pathlib import Path


class SizeScanner:
    def __init__(self, max_entries: int = 50000, timeout: float = 2):
        self.max_entries = max_entries
        self.deadline = time.monotonic() + timeout
        self.entries = 0
        self.seen: set[str] = set()

    def migration_copies(self, directory: Path) -> dict:
        paths = []
        try:
            with os.scandir(directory) as children:
                for child in children:
                    self.entries += 1
                    if self.entries >= self.max_entries or time.monotonic() > self.deadline:
                        return {"size_bytes": None, "file_count": None, "note": "统计达到读取上限，大小暂不可用。"}
                    name = child.name
                    if ((name.endswith(".bak") or (name.startswith("hub.before-") and name.endswith(".db")))
                            and child.is_file(follow_symlinks=False)):
                        paths.append(Path(child.path))
        except FileNotFoundError:
            return {"size_bytes": 0, "file_count": 0, "note": "目录尚不存在。"}
        except OSError:
            return {"size_bytes": None, "file_count": None, "note": "历史副本目录无法读取。"}
        return self.measure(paths)

    def measure(self, paths: list[Path]) -> dict:
        size = count = 0
        found = False
        skipped = False
        pending = list(paths)
        try:
            while pending:
                if self.entries >= self.max_entries or time.monotonic() > self.deadline:
                    return {"size_bytes": None, "file_count": None, "note": "统计达到读取上限，请稍后刷新或缩小目录规模。"}
                path = pending.pop()
                self.entries += 1
                if path.is_symlink() or path.is_junction():
                    skipped = True
                    continue
                key = os.path.normcase(os.path.abspath(path))
                if key in self.seen:
                    continue
                self.seen.add(key)
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                found = True
                if path.is_dir():
                    with os.scandir(path) as children:
                        for child in children:
                            if len(pending) + self.entries >= self.max_entries or time.monotonic() > self.deadline:
                                return {"size_bytes": None, "file_count": None, "note": "统计达到读取上限，大小暂不可用。"}
                            pending.append(Path(child.path))
                elif path.is_file():
                    size += stat.st_size
                    count += 1
        except OSError:
            return {"size_bytes": None, "file_count": None, "note": "部分文件无法读取，未将不完整结果计入总占用。"}
        note = "已跳过符号链接或目录联接。" if skipped else ""
        if not found and not skipped:
            note = "当前没有可统计的文件；路径尚不存在或已计入其他存储项。"
        return {"size_bytes": size, "file_count": count, "note": note}


def sqlite_files(path: Path) -> list[Path]:
    return [path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")]
