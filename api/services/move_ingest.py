from __future__ import annotations

import json
import re
import time
import uuid
from typing import Dict, List, Optional

from psycopg.types.json import Json

from api.channelizers import run_channels


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentence_split(text: str) -> List[str]:
    """Split raw text into sentences while keeping punctuation heuristically."""
    text = (text or "").strip()
    if not text:
        return []
    if not SENT_SPLIT.search(text):
        return [text]
    return [segment.strip() for segment in SENT_SPLIT.split(text) if segment.strip()]


def default_session_id(domain: str) -> str:
    """Build a stable session identifier for ingest endpoints."""
    return f"{domain}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"


def ingest_one_text(
    conn,
    text: str,
    *,
    session_id: str,
    domain: str,
    used_channels: Optional[List[str]] = None,
    span: Optional[dict] = None,
    prev_by_channel: Optional[Dict[str, int]] = None,
) -> Dict[str, any]:
    """
    Run channels over a single text snippet, insert move rows, and link edges.

    Returns a small summary that callers can use to accumulate results across
    a batch ingest.
    """
    if not text or not text.strip():
        return {
            "move_for_channel": {},
            "prev_by_channel": prev_by_channel or {},
            "moves": 0,
            "edges": 0,
        }

    channel_vectors = run_channels(text, used_channels)
    move_for_channel: Dict[str, int] = {}
    edges_made = 0
    span = span or {}
    prev_by_channel = dict(prev_by_channel or {})

    with conn.cursor() as cur:
        for channel, vec in channel_vectors.items():
            cur.execute(
                """
                INSERT INTO move (session_id, domain, channel, span, features)
                VALUES (%s,%s,%s,%s, (%s)::float8[]::vector(384))
                RETURNING id
                """,
                (session_id, domain, channel, Json(span), vec),
            )
            move_id = cur.fetchone()["id"]
            move_for_channel[channel] = move_id

            prev_move = prev_by_channel.get(channel)
            if prev_move:
                cur.execute(
                    """
                    INSERT INTO move_edge (source_move, target_move, channel, delta, weight, freq, last_seen, context)
                    SELECT %s, %s, %s,
                           (m2.features - m1.features),
                           0.0, 1, now(), %s
                    FROM (SELECT features FROM move WHERE id=%s) m1,
                         (SELECT features FROM move WHERE id=%s) m2
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        prev_move,
                        move_id,
                        channel,
                        Json({"domain": domain, "session_id": session_id}),
                        prev_move,
                        move_id,
                    ),
                )
                edges_made += 1

            prev_by_channel[channel] = move_id

    return {
        "move_for_channel": move_for_channel,
        "prev_by_channel": prev_by_channel,
        "moves": len(move_for_channel),
        "edges": edges_made,
    }

