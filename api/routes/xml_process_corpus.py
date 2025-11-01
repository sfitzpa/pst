# api/routes/xml_process_corpus.py
from fastapi import APIRouter, HTTPException, Body
import asyncpg, os
from typing import Optional, Dict, Any

from api.services.corpus_processing import (
    ensure_pst_tables,
    parse_xml_bytes,
    upsert_doc_unit,
    write_moves,
)

router = APIRouter()
POOL = None

async def pool():
    global POOL
    if POOL is None:
        POOL = await asyncpg.create_pool(
            dsn=os.getenv("DATABASE_URL", "postgresql://pst:pstpass@pst-postgres:5432/pst"),
            min_size=1, max_size=5
        )
    return POOL

@router.post("/xml/process_corpus")
async def process_corpus(
    corpus_id: Optional[int] = Body(None),
    domain: Optional[str] = Body(None),
    recompute_curvature: bool = Body(False),
    session_prefix: Optional[str] = Body("CORPUS")
) -> Dict[str, Any]:
    if not corpus_id and not domain:
        raise HTTPException(400, "Provide corpus_id or domain.")
    async with (await pool()).acquire() as con:
        # shape: id, domain, doc_key, xml_payload, session_hint
        if corpus_id:
            rows = await con.fetch(
                """
                SELECT id,
                       domain,
                       doc_key,
                       xml_payload,
                       COALESCE(meta->>'session_hint', '') AS session_hint
                FROM corpus_xml
                WHERE id=$1
                """,
                corpus_id,
            )
        else:
            rows = await con.fetch(
                """
                SELECT id,
                       domain,
                       doc_key,
                       xml_payload,
                       COALESCE(meta->>'session_hint', '') AS session_hint
                FROM corpus_xml
                WHERE domain=$1
                """,
                domain,
            )

        if not rows:
            raise HTTPException(404, "No matching corpus_xml rows.")
        await ensure_pst_tables(con)

        totals = 0
        for r in rows:
            payload = r["xml_payload"]
            if isinstance(payload, (bytes, bytearray, memoryview)):
                xml_bytes = bytes(payload)
            else:
                xml_bytes = str(payload).encode("utf-8")
            dom = r["domain"]
            doc_key = r["doc_key"]
            units = parse_xml_bytes(xml_bytes, dom, doc_key)
            if not units:
                continue
            session_hint = r["session_hint"] or doc_key
            session_id = f"{session_prefix}_{session_hint}"
            async with con.transaction():
                await upsert_doc_unit(con, session_id, dom, units)
                await write_moves(con, session_id, dom, units)
                totals += len(units)

        if recompute_curvature and totals:
            await (await pool()).execute("SELECT rebuild_curvature_multi();")

        return {"processed_units": totals, "rows_seen": len(rows), "recomputed_curvature": bool(recompute_curvature)}
