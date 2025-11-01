from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lxml import etree

from api.channelizers import run_channels


PATH_SANITIZER = re.compile(r"[^A-Za-z0-9_]+")


def _sanitize_token(token: str) -> str:
    cleaned = PATH_SANITIZER.sub("_", token).strip("_")
    return cleaned or "unit"


def _collapse_tail_text(node: etree._Element) -> Optional[str]:
    """Collect direct textual content without duplicating descendant text."""
    parts: List[str] = []
    if node.text and node.text.strip():
        parts.append(node.text.strip())
    for child in node:
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    text = " ".join(parts).strip()
    return text or None


def parse_xml_bytes(xml_bytes: bytes | bytearray | memoryview | str, domain: str, doc_key: str) -> List[Dict[str, Any]]:
    """
    Convert raw XML into a flat list of unit dicts ready for persistence.

    Each unit carries the minimal metadata necessary to create doc_unit rows and
    later derive channel moves.
    """
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    elif isinstance(xml_bytes, memoryview):
        xml_bytes = xml_bytes.tobytes()
    else:
        xml_bytes = bytes(xml_bytes)

    root = etree.fromstring(xml_bytes)
    counters: Dict[Tuple[Optional[str], str], int] = defaultdict(int)
    units: List[Dict[str, Any]] = []

    def walk(node: etree._Element, parent_path: Optional[str]) -> None:
        tag = etree.QName(node).localname
        kind = _sanitize_token(tag.lower())
        counter_key = (parent_path, kind)
        counters[counter_key] += 1
        ordinal = counters[counter_key]
        path = f"{parent_path}.{kind}.{ordinal:03d}" if parent_path else f"{kind}.{ordinal:03d}"

        label = node.get("label") or node.get("name") or node.get("title") or node.get("id")
        meta = {k: v for k, v in node.attrib.items() if k not in {"label", "name", "title", "id"}}
        meta["tag"] = tag  # preserve original casing

        text = _collapse_tail_text(node)

        units.append(
            {
                "domain": domain,
                "doc_key": doc_key,
                "kind": kind,
                "label": label,
                "path": path,
                "ordinal": ordinal,
                "text": text,
                "meta": meta,
                "parent_path": parent_path,
            }
        )

        for child in node:
            if isinstance(child.tag, str):  # skip comments / processing instructions
                walk(child, path)

    walk(root, None)
    return units


async def ensure_pst_tables(conn) -> None:
    """Create the core PST tables if they are missing."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_unit (
            id         BIGSERIAL PRIMARY KEY,
            domain     TEXT NOT NULL,
            doc_key    TEXT NOT NULL,
            kind       TEXT NOT NULL,
            label      TEXT,
            path       LTREE NOT NULL,
            ordinal    INTEGER,
            text       TEXT,
            meta       JSONB,
            parent_id  BIGINT REFERENCES doc_unit(id) ON DELETE CASCADE
        );
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS doc_unit_domain_idx ON doc_unit (domain)")
    await conn.execute("CREATE INDEX IF NOT EXISTS doc_unit_kind_idx ON doc_unit (kind)")
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS doc_unit_uq_path ON doc_unit (domain, doc_key, path)")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS move (
            id         BIGSERIAL PRIMARY KEY,
            session_id TEXT,
            domain     TEXT,
            channel    TEXT,
            span       JSONB,
            features   VECTOR(384),
            created_at TIMESTAMPTZ DEFAULT now(),
            frame_id   INTEGER
        );
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS move_domain_channel_idx ON move (domain, channel)")
    await conn.execute("CREATE INDEX IF NOT EXISTS move_session_id_idx ON move (session_id)")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS move_edge (
            id          BIGSERIAL PRIMARY KEY,
            source_move BIGINT REFERENCES move(id) ON DELETE CASCADE,
            target_move BIGINT REFERENCES move(id) ON DELETE CASCADE,
            channel     TEXT,
            delta       VECTOR(384),
            weight      DOUBLE PRECISION DEFAULT 0.0,
            freq        INTEGER DEFAULT 0,
            last_seen   TIMESTAMPTZ DEFAULT now(),
            context     JSONB
        );
        """
    )
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS move_edge_uniq ON move_edge (source_move, target_move, channel)")
    await conn.execute("CREATE INDEX IF NOT EXISTS move_edge_channel_idx ON move_edge (channel)")


async def upsert_doc_unit(conn, session_id: str, domain: str, units: Iterable[Dict[str, Any]]) -> int:
    """
    Replace doc_unit rows for the supplied units and return count inserted.

    The units iterable is expected to come from parse_xml_bytes.
    """
    units = list(units)
    if not units:
        return 0

    doc_key = units[0]["doc_key"]
    await conn.execute("DELETE FROM doc_unit WHERE domain=$1 AND doc_key=$2", domain, doc_key)

    path_to_id: Dict[str, int] = {}
    inserted = 0
    for unit in units:
        parent_id = path_to_id.get(unit.get("parent_path"))
        row = await conn.fetchrow(
            """
            INSERT INTO doc_unit (domain, doc_key, kind, label, path, ordinal, text, meta, parent_id)
            VALUES ($1,$2,$3,$4,$5::ltree,$6,$7,$8::jsonb,$9)
            ON CONFLICT (domain, doc_key, path)
            DO UPDATE SET
                kind = EXCLUDED.kind,
                label = EXCLUDED.label,
                ordinal = EXCLUDED.ordinal,
                text = EXCLUDED.text,
                meta = EXCLUDED.meta,
                parent_id = EXCLUDED.parent_id
            RETURNING id
            """,
            domain,
            unit["doc_key"],
            unit["kind"],
            unit.get("label"),
            unit["path"],
            unit.get("ordinal"),
            unit.get("text"),
            json.dumps(unit.get("meta") or {}),
            parent_id,
        )
        if row:
            unit_id = row["id"]
            path_to_id[unit["path"]] = unit_id
            inserted += 1

    return inserted


async def write_moves(conn, session_id: str, domain: str, units: Iterable[Dict[str, Any]]) -> int:
    """
    Materialize channel moves from unit text and return number of moves inserted.
    """
    prev_by_channel: Dict[str, Tuple[int, List[float]]] = {}
    inserted = 0

    for unit in units:
        text = (unit.get("text") or "").strip()
        if not text:
            continue

        span = {
            "doc_key": unit["doc_key"],
            "path": unit["path"],
            "kind": unit["kind"],
            "ordinal": unit.get("ordinal"),
        }

        channel_vectors = run_channels(text)
        for channel, vec in channel_vectors.items():
            row = await conn.fetchrow(
                """
                INSERT INTO move (session_id, domain, channel, span, features)
                VALUES ($1,$2,$3,$4::jsonb,$5::float8[]::vector(384))
                RETURNING id
                """,
                session_id,
                domain,
                channel,
                json.dumps(span),
                vec,
            )
            if not row:
                continue

            move_id = row["id"]
            prev_entry = prev_by_channel.get(channel)
            if prev_entry:
                prev_id, prev_vec = prev_entry
                delta = [curr - prev for curr, prev in zip(vec, prev_vec)]
                await conn.execute(
                    """
                    INSERT INTO move_edge (source_move, target_move, channel, delta, weight, freq, last_seen, context)
                    VALUES ($1,$2,$3,$4::float8[]::vector(384),0.0,1,now(),$5::jsonb)
                    ON CONFLICT (source_move, target_move, channel) DO NOTHING
                    """,
                    prev_id,
                    move_id,
                    channel,
                    delta,
                    json.dumps({"session_id": session_id, "domain": domain}),
                )

            prev_by_channel[channel] = (move_id, list(vec))
            inserted += 1

    return inserted

