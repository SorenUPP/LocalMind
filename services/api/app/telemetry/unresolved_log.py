"""Logs prompts the local model couldn't resolve, so they can be reviewed and
used later to fine-tune / few-shot the local model.

Each line in the log file is one JSON record:
    {"timestamp": ..., "dataset": ..., "user_query": ..., "reason": ..., "details": ...}
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_LOCK = Lock()


def _log_path() -> Path:
    path = Path(os.getenv("UNRESOLVED_PROMPTS_LOG", "data/unresolved_prompts.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_unresolved_prompt(user_query: str, dataset: str | None, reason: str, details: object = None) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "user_query": user_query,
        "reason": reason,
        "details": details,
    }
    line = json.dumps(record, ensure_ascii=False)
    # Simple append-only write. Good enough for low/medium request volume;
    # if this becomes a bottleneck, move the write to a background task queue.
    with _LOCK:
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
