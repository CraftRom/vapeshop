"""Bounded Telegram HTML generated from escaped values, without lost text.

Count UTF-16 units conservatively, including markup. Split only between
complete tags/entities/code points and close/reopen formatting on every page.
This accepts application-generated HTML, never raw customer HTML.
"""
from __future__ import annotations

import re

MESSAGE_LIMIT = 3500
CAPTION_LIMIT = 1000
_TOKENS = re.compile(r"<[^>]+>|&(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]+);|.", re.S)


def units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_html(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    if limit < 64:
        raise ValueError("HTML chunk budget is too small")
    chunks, parts, stack = [], [], []
    size = 0
    closing = ""
    for token in _TOKENS.findall(text):
        next_stack = list(stack)
        if token.startswith("</"):
            tag = token[2:-1].strip()
            if not next_stack or next_stack[-1][0] != tag:
                raise ValueError("Unbalanced application HTML")
            next_stack.pop()
        elif token.startswith("<"):
            tag = token[1:-1].split()[0]
            next_stack.append((tag, token))
        next_closing = "".join(f"</{tag}>" for tag, _ in reversed(next_stack))
        if size + units(token) + units(next_closing) > limit:
            if not parts or size + units(closing) > limit:
                raise ValueError("HTML token exceeds the chunk budget")
            chunks.append("".join(parts) + closing)
            parts = [opening for _, opening in stack]
            size = sum(units(part) for part in parts)
            if size + units(token) + units(next_closing) > limit:
                raise ValueError("HTML token exceeds the chunk budget")
        parts.append(token)
        size += units(token)
        stack, closing = next_stack, next_closing
    if stack:
        raise ValueError("Unclosed application HTML")
    if parts:
        chunks.append("".join(parts))
    return chunks


async def answer_html(message, text: str, *, reply_markup=None, **kwargs):
    chunks = split_html(text)
    result = None
    for index, chunk in enumerate(chunks):
        result = await message.answer(
            chunk, reply_markup=reply_markup if index == len(chunks) - 1 else None,
            **kwargs,
        )
    return result


async def send_html(bot, chat_id, text: str, *, reply_markup=None, **kwargs):
    chunks = split_html(text)
    result = None
    for index, chunk in enumerate(chunks):
        result = await bot.send_message(
            chat_id, chunk, reply_markup=reply_markup if index == len(chunks) - 1 else None,
            **kwargs,
        )
    return result
