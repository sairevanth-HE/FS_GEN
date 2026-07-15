"""Question ID minting per generator.md's Output-location rule."""

from __future__ import annotations

import uuid
from pathlib import Path


def generate_question_id(stack_slug: str, difficulty: str, generated_dir: Path) -> str:
    """Return `<stack-slug>-<difficulty>-<4hex>` with a suffix not already used
    under generated/ for that stack+difficulty (directories never collide)."""
    while True:
        qid = f"{stack_slug}-{difficulty.lower()}-{uuid.uuid4().hex[:4]}"
        if not (generated_dir / qid).exists():
            return qid
