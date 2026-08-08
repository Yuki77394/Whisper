"""
WhisperX – input parser.

Accepts BOTH orderings:

    @Bot @user Hello bro          (recipient-first)
    @Bot Hello bro @user          (message-first)

Also handles:
    @Bot @user1 @user2 Hi team    (chained recipients)
    @Bot Hello @user1 and @user2  (only the trailing @user2 is a recipient;
                                    the middle @user1 is treated as prose
                                    unless explicitly preceded by 'to'/'for')

Returns a ParseResult with:
  - recipient_handles (unique list, order preserved)
  - content (the actual message, with recipient @mentions removed
    where they are clearly recipient tokens)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Telegram usernames: 5–32 chars, [A-Za-z0-9_], must start with a letter.
USERNAME_RE = re.compile(r"(?<![\w])@([A-Za-z][A-Za-z0-9_]{3,31})\b")
# Numeric telegram user id (rare in inline text, but supported)
NUMID_RE = re.compile(r"(?<![\w])#id(\d{4,12})\b")


@dataclass
class ParseResult:
    recipient_handles: List[str] = field(default_factory=list)
    recipient_ids: List[int] = field(default_factory=list)
    content: str = ""
    raw: str = ""
    has_recipient: bool = False
    is_public: bool = False  # when no recipient -> anyone in chat can open
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.error is None and bool(self.content) or self.is_public


# ────────────────────────────────────────────────────────────────────
def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Remove the leading @BotUsername if present."""
    if not bot_username:
        return text
    bu = bot_username.lstrip("@")
    pat = re.compile(rf"^@{re.escape(bu)}\b\s*", re.IGNORECASE)
    return pat.sub("", text, count=1).lstrip()


def _find_username_tokens(text: str) -> List[Tuple[int, int, str]]:
    """Return [(start, end, username_lower), ...] for every @username match."""
    return [(m.start(), m.end(), m.group(1).lower()) for m in USERNAME_RE.finditer(text)]


def _find_numeric_ids(text: str) -> List[Tuple[int, int, int]]:
    return [(m.start(), m.end(), int(m.group(1))) for m in NUMID_RE.finditer(text)]


def _classify_mentions(
    text: str, matches: List[Tuple[int, int, str]]
) -> Tuple[List[Tuple[int, int, str]], List[Tuple[int, int, str]]]:
    """
    Split matches into (recipients, prose) lists.

    A mention is a recipient if any of:
      1. It is at the very start of the text (prefix is empty/whitespace).
      2. It is at the very end of the text (suffix is empty/whitespace).
      3. It is immediately preceded by another recipient mention + whitespace
         (i.e. part of a chained recipient list).
      4. It is immediately preceded by the word 'to' / 'for' / '->' / '→'.
    """
    recipients: List[Tuple[int, int, str]] = []
    prose: List[Tuple[int, int, str]] = []

    last_recipient_end = -1  # end index of the previous recipient mention

    for i, (start, end, name) in enumerate(matches):
        prefix = text[:start]
        suffix = text[end:]
        prefix_stripped = prefix.rstrip()
        suffix_stripped = suffix.lstrip()

        is_edge_start = prefix_stripped == ""
        is_edge_end = suffix_stripped == ""

        # Chained: previous recipient ended right before this one (only whitespace between)
        is_chained = (
            last_recipient_end != -1
            and prefix_stripped != ""
            and text[last_recipient_end:start].strip() == ""
        )

        # Preceded by 'to'/'for'/'->'/'→'
        kw_match = re.search(r"(\w+|[->→]+)\s*$", prefix_stripped)
        is_kw = bool(kw_match) and kw_match.group(1).lower() in {
            "to", "for", "to:", "for:", "->", "→", ">>"
        }

        if is_edge_start or is_edge_end or is_chained or is_kw:
            recipients.append((start, end, name))
            last_recipient_end = end
        else:
            prose.append((start, end, name))
            # Don't update last_recipient_end — chain is broken.

    return recipients, prose


# ────────────────────────────────────────────────────────────────────
def parse_whisper_input(
    raw_text: str,
    *,
    bot_username: str = "",
    replied_recipient: Optional[str] = None,
    replied_recipient_id: Optional[int] = None,
) -> ParseResult:
    """
    Main entry point.

    `replied_recipient` is the username of the user whose message was replied to
    in the group (if any). When present, it's used as recipient only if no
    explicit @recipient was supplied.
    """
    if raw_text is None:
        return ParseResult(error="Empty input.", raw="")
    raw = raw_text.strip()
    if not raw:
        return ParseResult(error="Empty input.", raw=raw_text)

    text = _strip_bot_mention(raw, bot_username)
    if not text.strip():
        return ParseResult(error="Empty input.", raw=raw_text)

    matches = _find_username_tokens(text)
    num_ids = _find_numeric_ids(text)

    recipient_matches, _prose_matches = _classify_mentions(text, matches)

    recipient_handles: List[str] = []
    recipient_spans: List[Tuple[int, int]] = []
    for s, e, name in recipient_matches:
        if name not in recipient_handles:
            recipient_handles.append(name)
            recipient_spans.append((s, e))

    recipient_ids: List[int] = [nid for _, _, nid in num_ids]

    # Build the list of (start, end) spans to remove from the message text.
    # For each recipient mention we MAY extend its start leftward to cover a
    # leading keyword like 'to' / 'for' / '->' / '→'. The recipient span itself
    # is added only once (either extended or original).
    spans_to_remove: List[Tuple[int, int]] = []

    for s, e, _ in recipient_matches:
        new_start = s
        prefix = text[:s].rstrip()
        m = re.search(r"(\w+|[->→]+)\s*$", prefix)
        if m and m.group(1).lower() in {"to", "for", "to:", "for:", "->", "→", ">>"}:
            new_start = len(prefix) - len(m.group(0))
        spans_to_remove.append((new_start, e))

    # Numeric #id tokens
    spans_to_remove.extend((s, e) for s, e, _ in num_ids)

    # Merge overlapping / adjacent spans so we never apply conflicting offsets
    spans_to_remove.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans_to_remove:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    for s, e in reversed(merged):
        text = text[:s] + text[e:]

    text = text.strip()
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"[\-\:\→\>\s]+$", "", text).strip()
    text = re.sub(r"^[\-\:\→\>\s]+", "", text).strip()

    # Fallback to replied user
    if not recipient_handles and not recipient_ids and replied_recipient:
        recipient_handles.append(replied_recipient.lstrip("@").lower())
    if not recipient_ids and replied_recipient_id and not recipient_handles:
        recipient_ids.append(replied_recipient_id)

    if not recipient_handles and not recipient_ids and not replied_recipient:
        # Public whisper (no specific recipient).
        return ParseResult(
            recipient_handles=[],
            recipient_ids=[],
            content=text,
            raw=raw_text,
            has_recipient=False,
            is_public=True,
        )

    if not text:
        return ParseResult(
            recipient_handles=recipient_handles,
            recipient_ids=recipient_ids,
            content="",
            raw=raw_text,
            has_recipient=True,
            is_public=False,
            error="No message content.",
        )

    return ParseResult(
        recipient_handles=recipient_handles,
        recipient_ids=recipient_ids,
        content=text,
        raw=raw_text,
        has_recipient=True,
        is_public=False,
    )
