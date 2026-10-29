"""Stage LangGraph checkpoints; persist them atomically with domain changes.

LangGraph invokes savers on worker threads. This buffer avoids sharing SQLAlchemy
sessions between threads. A failed request rolls back both graph and domain state.
"""

import base64
from threading import RLock

from langgraph.checkpoint.base import WRITES_IDX_MAP, BaseCheckpointSaver, CheckpointTuple


def config_for(thread: str, namespace: str, checkpoint_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread,
            "checkpoint_ns": namespace,
            "checkpoint_id": checkpoint_id,
        }
    }


class TransactionalSaver(BaseCheckpointSaver):
    def __init__(self, payload: dict | None = None):
        super().__init__()
        self.rows = (payload or {}).get("checkpoints", {})
        self.writes = (payload or {}).get("writes", {})
        self.lock = RLock()

    def encode(self, value) -> list[str]:
        kind, data = self.serde.dumps_typed(value)
        return [kind, base64.b64encode(data).decode("ascii")]

    def decode(self, value):
        return self.serde.loads_typed((value[0], base64.b64decode(value[1])))

    def get_tuple(self, config) -> CheckpointTuple | None:
        with self.lock:
            opts = config["configurable"]
            thread, namespace = opts["thread_id"], opts.get("checkpoint_ns", "")
            rows = [
                r
                for r in self.rows.values()
                if r["thread"] == thread
                and r["namespace"] == namespace
                and (not opts.get("checkpoint_id") or r["id"] == opts["checkpoint_id"])
            ]
            if not rows:
                return None
            row = max(rows, key=lambda r: r["id"])
            writes = self.writes.get(row["id"], {})
            return CheckpointTuple(
                config=config_for(thread, namespace, row["id"]),
                checkpoint=self.decode(row["checkpoint"]),
                metadata=self.decode(row["metadata"]),
                parent_config=config_for(thread, namespace, row["parent"])
                if row["parent"]
                else None,
                pending_writes=[
                    (w["task"], w["channel"], self.decode(w["value"])) for w in writes.values()
                ],
            )

    def put(self, config, checkpoint, metadata, new_versions):
        with self.lock:
            opts = config["configurable"]
            checkpoint_id = checkpoint["id"]
            self.rows[checkpoint_id] = {
                "thread": opts["thread_id"],
                "namespace": opts.get("checkpoint_ns", ""),
                "id": checkpoint_id,
                "parent": opts.get("checkpoint_id"),
                "checkpoint": self.encode(checkpoint),
                "metadata": self.encode(metadata),
            }
            return config_for(opts["thread_id"], opts.get("checkpoint_ns", ""), checkpoint_id)

    def put_writes(self, config, writes, task_id, task_path="") -> None:
        with self.lock:
            stored = self.writes.setdefault(config["configurable"]["checkpoint_id"], {})
            for index, (channel, value) in enumerate(writes):
                position = WRITES_IDX_MAP.get(channel, index)
                key = f"{task_id}:{position}"
                if position >= 0 and key in stored:
                    continue
                stored[key] = {"task": task_id, "channel": channel, "value": self.encode(value)}

    def export(self) -> dict:
        with self.lock:
            return {"checkpoints": self.rows, "writes": self.writes}
