"""向量索引存储：Chroma 持久化 + DashScope Embedding 的构建/增量/检索。

目录结构（与归一化库隔离，向量数据不写入现有 SQLite）：
    GetWechatInfo/VectorStore/chroma_db/

索引模型：
- 每个 Chunk 一条 Chroma 文档；文档 ID = Chunk.chunk_id（确定性），
  同一批消息 ID 永远得到同一文档 ID，天然防重复写入；
- 元数据携带 chat_id / date / start_ts / end_ts / msg_ids(逗号分隔) /
  senders / content_hash，支持按群、按日期过滤，并可识别"消息被修改"
  （边界不变但 content_hash 变化 → upsert 覆盖旧记录）;
- 索引进度记录在独立集合 rag_state（每群一条：已覆盖到的消息 ID/时间戳、
  文档数、消息总数），增量构建只处理上次之后的新消息，失败不影响旧索引。

Embedding 走 DashScope OpenAI 兼容接口（/compatible-mode/v1/embeddings,
model=text-embedding-v4），实测与 Chat Completion 同 key 同 base_url,
支持批量输入，自动按 BATCH_SIZE 分批。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from .chunking import Chunk, chunk_messages

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from env_bootstrap import load_hub_env

load_hub_env()  # 独立运行（建索引脚本）也能读到 DASHSCOPE_API_KEY（权威源在用户目录）

logger = logging.getLogger(__name__)

CHROMA_DIR = ROOT_DIR / "GetWechatInfo" / "VectorStore" / "chroma_db"
COLLECTION_NAME = "chat_chunks"
STATE_COLLECTION_NAME = "rag_state"

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_BATCH_SIZE = 10  # DashScope 兼容模式 embeddings 接口单批上限(实测>10报400)


class DashScopeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma 嵌入函数：调用 DashScope 兼容模式的 embeddings 接口。

    实测（见开发记录）：POST {base_url}/embeddings,model=text-embedding-v4,
    返回 1024 维向量，input 支持字符串列表；与 Chat Completion 共用 key。
    """

    def __init__(self, api_key: str, base_url: str, model: str = EMBEDDING_MODEL):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
        self._model = model

    def name(self) -> str:
        return f"dashscope-embedding-{self._model}"

    def __call__(self, input: Documents) -> Embeddings:
        vectors: Embeddings = []
        total_tokens = 0  # Embedding 按输入 token 计费，无输出 token
        batches = 0
        for i in range(0, len(input), EMBEDDING_BATCH_SIZE):
            batch = input[i : i + EMBEDDING_BATCH_SIZE]
            response = self._client.embeddings.create(model=self._model, input=batch)
            vectors.extend(item.embedding for item in response.data)
            batches += 1
            usage = getattr(response, "usage", None)
            if usage:
                total_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        print(f"Embedding token 消耗: 输入 {total_tokens}（{batches} 批，模型 {self._model}）")
        return vectors


# ---------------------------------------------------------------- 连接与配置


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未找到 DASHSCOPE_API_KEY，请在 .env 中配置。")
    return key


def _base_url() -> str:
    # 复用 llm_config.json 的 base_url（与 Chat Completion 同一入口）
    from ..llm_config import _load_config

    return _load_config()["base_url"]


@lru_cache(maxsize=1)
def _client() -> chromadb.PersistentClient:
    CHROMA_DIR.parent.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )


@lru_cache(maxsize=1)
def _embedding_function() -> DashScopeEmbeddingFunction:
    return DashScopeEmbeddingFunction(api_key=_api_key(), base_url=_base_url())


def _collection() -> chromadb.Collection:
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def _state_collection() -> chromadb.Collection:
    return _client().get_or_create_collection(
        name=STATE_COLLECTION_NAME,
        embedding_function=_embedding_function(),
    )


# ---------------------------------------------------------------- 归一化库读取


def _connect() -> sqlite3.Connection:
    # 与 chat_tools._connect 同一约定：环境变量优先，物理只读
    configured = os.environ.get("WECHAT_AGENT_DB", "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"
    )
    if not path.exists():
        raise RuntimeError(f"找不到归一化聊天库 {path}，请先运行 normalize_snapshot.py。")
    # mode=ro：SQLite 层面的物理只读，索引构建绝不修改原始数据
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def list_chats() -> list[dict]:
    with _connect() as con:
        rows = con.execute("SELECT chat_id, display_name FROM chats").fetchall()
    return [{"chat_id": r["chat_id"], "name": r["display_name"]} for r in rows]


def _load_messages(chat_id: str, since_ts: int = 0) -> list[dict]:
    """读取某群消息（timestamp >= since_ts），按时间升序。"""

    with _connect() as con:
        rows = con.execute(
            """SELECT message_id, chat_id, timestamp, time, sender, text, msg_type
               FROM messages
               WHERE chat_id = ? AND timestamp >= ?
               ORDER BY timestamp""",
            (chat_id, since_ts),
        ).fetchall()
    return [dict(r) for r in rows]


def _chat_message_count(chat_id: str) -> int:
    with _connect() as con:
        return con.execute(
            "SELECT count(*) FROM messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]


# ---------------------------------------------------------------- 索引进度状态


def _get_state(chat_id: str) -> dict | None:
    """读取某群的索引进度；不存在返回 None。"""

    result = _state_collection().get(ids=[chat_id], include=["metadatas"])
    if not result["ids"]:
        return None
    return dict(result["metadatas"][0])


def _set_state(chat_id: str, **fields) -> None:
    metadata = {"chat_id": chat_id, **fields}
    _state_collection().upsert(ids=[chat_id], documents=[""], metadatas=[metadata])


# ---------------------------------------------------------------- Chunk 写入


def _upsert_chunks(chunks: list[Chunk]) -> None:
    if not chunks:
        return
    collection = _collection()
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "chat_id": c.chat_id,
                "date": c.date,
                "start_ts": c.start_ts,
                "end_ts": c.end_ts,
                "msg_ids": ",".join(str(i) for i in c.msg_ids),
                "senders": ",".join(c.senders),
                "content_hash": c.content_hash,
            }
            for c in chunks
        ],
    )


def _where(conditions: dict) -> dict:
    """组装 Chroma where 过滤：单条件直给，多条件必须 $and 包裹。"""

    items = [{k: v} for k, v in conditions.items() if v not in ("", None)]
    if len(items) <= 1:
        return items[0] if items else {}
    return {"$and": items}


def _delete_chunks(where: dict) -> None:
    """按元数据条件删除 Chunk（仅用于重建/尾部区间替换）。"""

    try:
        _collection().delete(where=where)
    except Exception:
        if where:  # chroma 不允许无条件 delete(where=None)，防御性兜底
            raise


# ---------------------------------------------------------------- 对外接口


def build_index(chat_id: str | None = None) -> dict[str, int]:
    """全量构建（或重建指定群）的向量索引。返回 {chat_id: chunk数}。

    已存在的确定性文档 ID 会被 upsert 覆盖，重复执行是安全的。
    """

    stats: dict[str, int] = {}
    for chat in list_chats():
        cid = chat["chat_id"]
        if chat_id and cid != chat_id:
            continue
        chunks = chunk_messages(_load_messages(cid))
        _delete_chunks({"chat_id": cid})
        _upsert_chunks(chunks)
        last = chunks[-1] if chunks else None
        _set_state(
            cid,
            last_msg_id=last.msg_ids[-1] if last else 0,
            last_chunk_start_ts=last.start_ts if last else 0,
            last_timestamp=last.end_ts if last else 0,
            chunk_count=len(chunks),
            total_msgs=_chat_message_count(cid),
            indexed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        stats[cid] = len(chunks)
        logger.info("全量索引 %s (%s): %d chunks", chat["name"], cid, len(chunks))
    return stats


def incremental_index() -> dict[str, int]:
    """增量索引所有群的新消息。返回 {chat_id: 新增chunk数（-1=失败）}。

    每群独立处理：单群失败只记日志、跳过（返回 -1），绝不影响其他群
    和已有索引，下次调用自动重试尾部。
    计数策略：总数**减少**才全量重建（历史数据被删/改）；总数不变或
    **增长**（同步新增）都走尾部增量——重叠窗口内边界 chunk 自动重切，
    未变化 chunk 的向量全部复用（阶段 3.6 调整，避免每次同步全群重建）。
    """

    stats: dict[str, int] = {}
    for chat in list_chats():
        cid = chat["chat_id"]
        try:
            state = _get_state(cid)
            if state is None:
                stats[cid] = build_index(cid)[cid]
                continue
            total = _chat_message_count(cid)
            indexed = int(state.get("total_msgs", -1))
            if indexed > total:
                logger.warning("%s 消息总数减少(%s->%d)，全量重建该群索引", cid, indexed, total)
                stats[cid] = build_index(cid)[cid]
                continue

            since = int(state["last_chunk_start_ts"])
            last_ts = int(state["last_timestamp"])
            messages = _load_messages(cid, since_ts=since)
            # 只有"上次最后一条之后"的消息才算新增；否则无事可做
            messages = [m for m in messages if m["timestamp"] > last_ts]
            if not messages:
                stats[cid] = 0
                continue

            # 先取旧尾部区间的文档 ID：重新切分后对比，清掉边界漂移产生的遗留
            old = _collection().get(
                where=_where({"chat_id": cid, "start_ts": {"$gte": since}}),
                include=[],
            )
            chunks = chunk_messages(messages)
            _upsert_chunks(chunks)  # 嵌入失败在此抛出，旧索引尚未动，保持可用
            stale = set(old["ids"]) - {c.chunk_id for c in chunks}
            if stale:
                _collection().delete(ids=list(stale))

            last = chunks[-1]
            _set_state(
                cid,
                last_msg_id=last.msg_ids[-1],
                last_chunk_start_ts=last.start_ts,
                last_timestamp=last.end_ts,
                chunk_count=int(state.get("chunk_count", 0)) + len(chunks) - len(old["ids"]),
                total_msgs=total,
                indexed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            stats[cid] = len(chunks)
            logger.info("增量索引 %s (%s): %d chunks", chat["name"], cid, len(chunks))
        except Exception:
            logger.exception("增量索引失败，跳过该群（已有索引不受影响）: %s", cid)
            stats[cid] = -1
    return stats


def rebuild_index() -> None:
    """删除整个向量索引并全量重建。"""

    client = _client()
    for name in (COLLECTION_NAME, STATE_COLLECTION_NAME):
        try:
            client.delete_collection(name)
        except Exception:
            pass  # 集合不存在（首次重建）时忽略
    _client.cache_clear()
    build_index()


def delete_index() -> None:
    """删除整个向量索引（含进度状态）。"""

    client = _client()
    for name in (COLLECTION_NAME, STATE_COLLECTION_NAME):
        try:
            client.delete_collection(name)
        except Exception:
            pass
    _client.cache_clear()


def index_exists() -> bool:
    # chroma>=1.5 的 list_collections() 返回 Collection 对象而非字符串，按名称比较
    return any(
        getattr(collection, "name", collection) == COLLECTION_NAME
        for collection in _client().list_collections()
    )


# ---------------------------------------------------------------- 语义检索


def search(
    query: str,
    date: str = "",
    chat_id: str = "",
    top_k: int = 10,
) -> list[dict]:
    """向量语义检索，返回命中 Chunk 列表（含文档正文与元数据）。

    按 chat_id / date 做元数据过滤；date 格式 YYYY-MM-DD。
    """

    where = _where({"chat_id": chat_id, "date": date})

    kwargs: dict = {
        "query_texts": [query],
        "n_results": max(1, min(int(top_k), 50)),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    result = _collection().query(**kwargs)
    hits = []
    for chunk_id, doc, meta, dist in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        hits.append(
            {
                "chunk_id": chunk_id,
                "text": doc,
                "distance": dist,
                "chat_id": meta.get("chat_id", ""),
                "date": meta.get("date", ""),
                "msg_ids": meta.get("msg_ids", "").split(","),
                "senders": [s for s in meta.get("senders", "").split(",") if s],
            }
        )
    return hits


if __name__ == "__main__":
    """命令行入口：python -m app.wechat_agent.normal_tools.rag_store [build|incremental|rebuild|delete|status]"""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "build":
        for cid, n in build_index().items():
            print(f"全量索引完成 {cid}: {n} chunks")
    elif command == "incremental":
        for cid, n in incremental_index().items():
            print(f"增量索引 {cid}: {'失败' if n < 0 else f'{n} chunks'}")
    elif command == "rebuild":
        rebuild_index()
        print("已删除并重建全部索引")
    elif command == "delete":
        delete_index()
        print("已删除全部索引")
    elif command == "status":
        for chat in list_chats():
            state = _get_state(chat["chat_id"])
            total = _chat_message_count(chat["chat_id"])
            if state:
                print(
                    f"{chat['name']}: 已索引 {state.get('chunk_count', 0)} chunks"
                    f"（消息 {state.get('total_msgs', '?')}/{total}，"
                    f"更新于 {state.get('indexed_at', '?')}）"
                )
            else:
                print(f"{chat['name']}: 未索引（共 {total} 条消息）")
    else:
        print(f"未知命令: {command}（可用: build/incremental/rebuild/delete/status）")
        sys.exit(1)
