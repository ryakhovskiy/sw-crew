"""Context window management — token estimation and history summarization."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimation based on character count.

    Uses the approximation of ~4 characters per token, which is
    conservative for English text.  This avoids a dependency on
    a tokenizer library.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # Tool-use blocks: each block may be a dict with text/content
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("content", "")))
                    total_chars += len(str(block.get("text", "")))
                else:
                    total_chars += len(str(block))
    return total_chars // 4


def summarize_history(
    client: Any,
    messages: list[dict[str, Any]],
    model: str,
    *,
    keep_last_turns: int = 2,
) -> list[dict[str, Any]]:
    """Compress older messages into a summary, keeping the last N turns.

    Parameters
    ----------
    client : anthropic.Anthropic
        Anthropic API client instance.
    messages : list[dict]
        Full conversation messages.
    model : str
        Model identifier.
    keep_last_turns : int
        Number of most-recent message pairs to keep verbatim.

    Returns
    -------
    list[dict]
        Compressed messages list with a summary replacing older turns.
    """
    if len(messages) <= keep_last_turns * 2:
        return messages  # nothing to compress

    # Split into "old" and "recent"
    cutoff = len(messages) - (keep_last_turns * 2)
    old_messages = messages[:cutoff]
    recent_messages = messages[cutoff:]

    # Build text representation of old messages for summarization
    old_text_parts = []
    for msg in old_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            old_text_parts.append(f"[{role}]: {content[:2000]}")
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    text_parts.append(str(block.get("content", block.get("text", "")))[:500])
            old_text_parts.append(f"[{role}]: {' '.join(text_parts)[:2000]}")

    old_text = "\n".join(old_text_parts)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=(
                "You are a precise summarizer. Summarize the following conversation "
                "history into a concise summary that preserves all key decisions, "
                "actions taken, files modified, and important context. "
                "Be specific about what was done and what remains."
            ),
            messages=[{"role": "user", "content": old_text}],
        )
        summary_text = response.content[0].text
    except Exception:
        logger.warning("Context summarization failed, keeping original messages")
        return messages

    # Replace old messages with summary
    summary_message = {
        "role": "user",
        "content": f"[Summary of previous conversation]\n{summary_text}",
    }
    # Need assistant acknowledgment for valid message sequence
    ack_message = {
        "role": "assistant",
        "content": "Understood. I have the context from the summary. Continuing.",
    }

    logger.info(
        "Summarized %d messages into summary (%d → %d tokens est.)",
        len(old_messages),
        estimate_tokens(old_messages),
        estimate_tokens([summary_message]),
    )

    return [summary_message, ack_message] + recent_messages
