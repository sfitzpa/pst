from fastapi import FastAPI
import os, math
from datetime import datetime, timedelta
import json

from fastapi import Body
from fastapi.middleware.cors import CORSMiddleware

# app.py (snippets)
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from api.channelizers import run_channels, CHANNELIZERS
from psycopg.types.json import Json
import time, uuid, re, psycopg
from psycopg.rows import dict_row

app = FastAPI()

# If you want to be strict, list your exact origins instead of ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # or ["http://pi-core:8090","http://localhost:8090"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URL = os.environ["DATABASE_URL"]

class ConceptIn(BaseModel):
    key: str
    label: str | None = None
    embedding: list[float]  # 1536-d by default

class ObservationIn(BaseModel):
    session_id: str
    sequence: list[str]     # list of concept.keys in order
    outcome: str = "success"
    context: dict | None = None

EMB_DIM = 3  # or 3 if you shrank the DB for the demo -- was 1536

def to_dim(x, d=EMB_DIM):
    """Pad/truncate any iterable to dimension d."""
    if isinstance(x, (list, tuple)):
        v = list(x)
    else:
        # psycopg may return the pgvector as text like "[0.1, 0.2, 0.3]"
        s = str(x).strip().lstrip("[({").rstrip("])}")
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        v = [float(p) for p in parts]
    if len(v) >= d:
        return v[:d]
    return v + [0.0] * (d - len(v))

def vec_sub(b, a, d=EMB_DIM):
    """Compute b - a with padding/truncation."""
    A = to_dim(a, d)
    B = to_dim(b, d)
    return [bj - aj for aj, bj in zip(A, B)]

		
# def vec_sub(b, a): return [bi - ai for ai, bi in zip(a, b, strict=True)]

@app.get("/health")
def health():
    try:
        with psycopg.connect(DB_URL) as conn:
            conn.execute("select 1")
        return {"status":"ok"}
    except Exception as e:
        return {"status":"db-fail","error":str(e)}

@app.get("/curvature/top")
def curvature_top(domain: str = "*", k: int = 20):
    q = """
    SELECT domain, ch_a, ch_b, COUNT(*) AS n, AVG(weight) AS w
    FROM curvature_multi
    WHERE (%s='*' OR domain=%s)
    GROUP BY 1,2,3
    ORDER BY w DESC NULLS LAST, n DESC
    LIMIT %s;
    """
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(q, (domain, domain, k))
        return [dict(r) for r in cur.fetchall()]

@app.get("/truths/recent")
def truths_recent(k: int = 20):
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("""
          SELECT id, claim, COALESCE(method,'') AS method,
                 ROUND(confidence::numeric,3) AS confidence, source, evidence
          FROM truth
          ORDER BY id DESC
          LIMIT %s
        """, (k,))
        return [dict(r) for r in cur.fetchall()]
        
@app.post("/concepts")
def upsert_concept(c: ConceptIn):
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id FROM concept WHERE key=%s", (c.key,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE concept SET label=%s, embedding=%s WHERE id=%s",
                            (c.label, to_dim(c.embedding), row["id"]))
                cid = row["id"]
            else:
                cur.execute("INSERT INTO concept (key, label, embedding) VALUES (%s,%s,%s) RETURNING id",
                            (c.key, c.label, to_dim(c.embedding)))
                cid = cur.fetchone()["id"]
            conn.commit()
    return {"id": cid, "key": c.key}

@app.post("/observe")
def observe(obs: ObservationIn):
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        # write raw sequence
        for i, k in enumerate(obs.sequence):
            cur.execute("SELECT id, embedding FROM concept WHERE key=%s", (k,))
            row = cur.fetchone()
            if not row: raise ValueError(f"unknown concept key {k}")
            cur.execute("INSERT INTO observation (session_id, seq, concept_id, outcome) VALUES (%s,%s,%s,%s)",
                        (obs.session_id, i, row[0], obs.outcome))
        # accumulate transitions and weights
        for i in range(len(obs.sequence)-1):
            a, b = obs.sequence[i], obs.sequence[i+1]
            cur.execute("SELECT id, embedding FROM concept WHERE key=%s", (a,))
            sa, ea = cur.fetchone()
            cur.execute("SELECT id, embedding FROM concept WHERE key=%s", (b,))
            sb, eb = cur.fetchone()

            # old and has str-str error:: delta = [eb[j]-ea[j] for j in range(len(eb))]
            # upsert trajectory
			# New way where we to_dim the values:: ea, eb come back as strings or lists; normalize then compute delta
            delta = vec_sub(eb, ea, EMB_DIM)

            cur.execute("""
              INSERT INTO trajectory (source_id, target_id, delta, weight, freq, last_seen, context)
              VALUES (%s,%s,%s, 0.0, 1, now(), %s)
              ON CONFLICT DO NOTHING
            """, (sa, sb, to_dim(delta, EMB_DIM), None))

            # update weight/freq
            cur.execute("""
              UPDATE trajectory
              SET freq = freq + 1,
                  weight = 1 - exp(-0.15 * (freq + 1)),
                  last_seen = now()
              WHERE source_id=%s AND target_id=%s
            """, (sa, sb))
        conn.commit()
    return {"status": "ok"}

@app.get("/predict/next/{key}")
def predict_next(key: str, k: int = 5):
    with psycopg.connect(DB_URL) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, embedding FROM concept WHERE key=%s", (key,))
        row = cur.fetchone()
        if not row: return {"predictions": []}
        source_id = row["id"]
        # naive: return top by weight/freq (fast baseline)
        cur.execute("""
          SELECT t.target_id, t.weight, t.freq, c.key AS target_key
          FROM trajectory t JOIN concept c ON c.id = t.target_id
          WHERE t.source_id = %s
          ORDER BY t.weight DESC, t.freq DESC
          LIMIT %s
        """, (source_id, k))
        return {"predictions": list(cur.fetchall())}

	
SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')
def sentence_split(x: str) -> List[str]:
    return [s.strip()] if (x := x.strip()) and not SENT_SPLIT.search(x) else \
           [s.strip() for s in SENT_SPLIT.split(x) if s.strip()]

class IngestBody(BaseModel):
    domain: str
    session_id: Optional[str] = None
    text: str
    channels: Optional[List[str]] = None  # None → all registered channels

def default_session_id(domain: str) -> str:
    return f"{domain}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"

# --- helper: ingest_one_text -----------------------------------------------
# Purpose: run selected channels on `text`, insert one move per channel,
# and (optionally) chain edges to the previous move in this stream.

def ingest_one_text(
    conn,
    text: str,
    *,
    session_id: str,
    domain: str,
    used_channels: Optional[List[str]] = None,   # None => all enabled
    span: Optional[dict] = None,                 # e.g., {"sent": i} or {"unit_path": "..."}
    prev_by_channel: Optional[Dict[str, int]] = None,  # carryover for chaining
) -> Dict[str, any]:
    """
    Returns:
      {
        "move_for_channel": {channel: move_id, ...},
        "prev_by_channel": {channel: move_id, ...},   # updated
        "moves": int,
        "edges": int
      }
    """
    if not text or not text.strip():
        return {"move_for_channel": {}, "prev_by_channel": prev_by_channel or {}, "moves": 0, "edges": 0}

    ch_map = run_channels(text, used_channels)   # {channel: np.array/list[384]}
    move_for_channel: Dict[str, int] = {}
    edges_made = 0
    span = span or {}
    prev_by_channel = dict(prev_by_channel or {})

    with conn.cursor() as cur:
        for ch, vec in ch_map.items():
            # Insert the move row with typed 384-d vector and span/context
            cur.execute("""
                INSERT INTO move (session_id, domain, channel, span, features)
                VALUES (%s,%s,%s,%s, (%s)::float8[]::vector(384))
                RETURNING id
            """, (session_id, domain, ch, Json(span), vec))
            mid = cur.fetchone()["id"]
            move_for_channel[ch] = mid

            # Build within-channel chain (prev -> curr)
            prev = prev_by_channel.get(ch)
            if prev:
                cur.execute("""
                    INSERT INTO move_edge (source_move, target_move, channel, delta, weight, freq, last_seen, context)
                    SELECT %s, %s, %s,
                           (m2.features - m1.features),
                           0.0, 1, now(), %s
                    FROM (SELECT features FROM move WHERE id=%s) m1,
                         (SELECT features FROM move WHERE id=%s) m2
                    ON CONFLICT DO NOTHING
                """, (prev, mid, ch, Json({"domain": domain, "session_id": session_id}), prev, mid))
                edges_made += 1

            prev_by_channel[ch] = mid

    return {
        "move_for_channel": move_for_channel,
        "prev_by_channel": prev_by_channel,
        "moves": len(move_for_channel),
        "edges": edges_made,
    }

@app.post("/ingest_text")
def ingest_text(body: IngestBody):
    sents = sentence_split(body.text)
    if not sents:
        return {"ok": True, "sentences": 0, "channel": body.channel}

    used_channels = None if (body.channel in (None, "", "all")) else [body.channel]

    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        prev_by_channel: Dict[str, int] = {}
        total_moves = 0
        total_edges = 0

        for i, sent in enumerate(sents):
            out = ingest_one_text(
                conn,
                sent,
                session_id=body.session_id,
                domain=body.domain,
                used_channels=used_channels,
                span={"sent": i, "ingest_source": "ingest_text"},
                prev_by_channel=prev_by_channel,
            )
            prev_by_channel = out["prev_by_channel"]
            total_moves += out["moves"]
            total_edges += out["edges"]

        conn.commit()

    return {
        "ok": True,
        "domain": body.domain,
        "session_id": sid,
        "sentences": len(sents),
        "channels": used_channels,
        "moves": total_moves,
        "edges": total_edges
    }

@app.post("/ingest_unit")
def ingest_unit(body: dict):
    unit_path = body["unit_path"]
    depth     = body.get("depth")           # e.g., "subtitle"
    channels  = body.get("channels")        # None => all
    wild = any(ch in unit_path for ch in "*?[]|{}")

    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        if depth:
            if wild:
                cur.execute("""
                  SELECT id, domain, doc_key, kind, label, path::text AS path, text, meta
                  FROM doc_unit WHERE path ~ %s::lquery AND kind = %s
                  ORDER BY path
                """, (unit_path, depth))
            else:
                cur.execute("""
                  SELECT id, domain, doc_key, kind, label, path::text AS path, text, meta
                  FROM doc_unit WHERE path <@ %s::ltree AND kind = %s
                  ORDER BY path
                """, (unit_path, depth))
        else:
            if wild:
                cur.execute("""
                  SELECT id, domain, doc_key, kind, label, path::text AS path, text, meta
                  FROM doc_unit WHERE path ~ %s::lquery ORDER BY path
                """, (unit_path,))
            else:
                cur.execute("""
                  SELECT id, domain, doc_key, kind, label, path::text AS path, text, meta
                  FROM doc_unit WHERE path = %s::ltree
                """, (unit_path,))

        rows = cur.fetchall()

        prev_by_channel: Dict[str, int] = {}
        total_moves = 0
        total_edges = 0

        for r in rows:
            out = ingest_one_text(
                conn,
                r["text"] or "",
                session_id=r["path"],                 # session id tied to unit path
                domain=r["domain"],
                used_channels=channels,
                span={"unit_id": r["id"], "kind": r["kind"], "label": r["label"]},
                prev_by_channel=prev_by_channel,
            )
            prev_by_channel = out["prev_by_channel"]
            total_moves += out["moves"]
            total_edges += out["edges"]

        conn.commit()

    return {"ok": True, "ingested": len(rows), "moves": total_moves, "edges": total_edges}


def to_int(x): 
    try: return int(x)
    except: return None

def build_path(scheme: str, ordinal: int, meta: dict) -> str:
    # e.g., "H.{ordinal:03d}" or "PRV.{meta.chapter}.{ordinal:02d}"
    return scheme.format(ordinal=ordinal, meta=meta)

@app.post("/xml/explode")
def xml_explode(body: dict):
    domain = body["domain"]
    doc_key = body["doc_key"]
    rules = body["rules"]
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, xml_payload FROM corpus_xml WHERE doc_key=%s AND domain=%s", (doc_key, domain))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "corpus_xml not found"}
        xml = etree.fromstring(bytes(row["xml_payload"], "utf-8")) if isinstance(row["xml_payload"], str) else etree.fromstring(row["xml_payload"])
        root = xml.xpath(rules.get("root_path","/"))[0]

        # helper: upsert unit, return id
        def insert_unit(kind, label, path, ordinal, text, meta, parent_id=None):
            cur.execute("""
              INSERT INTO doc_unit (domain, doc_key, kind, label, path, ordinal, text, meta, parent_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (domain, doc_key, kind, label, path, ordinal, text, Json(meta), parent_id))
            return cur.fetchone()["id"]

        ids_by_xpathnode = {}

        # pass 1: create primary units
        for u in rules["units"]:
            for node in root.xpath(u["path"]):
                label = (node.get(u.get("label_attr","")) or "").strip() or None
                ordinal = to_int(node.xpath(u["ordinal"])[0] if u.get("ordinal") else None)
                text = " ".join(node.xpath(u.get("text_path","./text()"))) if u.get("text_path") else None
                meta = {}
                for k,v in (u.get("meta") or {}).items():
                    meta[k] = (node.xpath(v)[0] if v.startswith("@") or v.startswith("./") or v.startswith("../") else v)

                # build ltree path
                if "path_scheme" in rules:
                    path = build_path(rules["path_scheme"], ordinal or 0, meta)
                else:
                    # fallback: KIND.ordinal
                    path = f"{u['kind']}.{ordinal or 0}"

                unit_id = insert_unit(u["kind"], label, path, ordinal, text, meta, parent_id=None)
                ids_by_xpathnode[node] = unit_id

                # optional sentence splitting for this unit
                for child in (rules.get("children",{}).get(u["kind"], [])):
                    if child.get("split") == "sentence" and text:
                        sentences = sentence_split(text)  # your splitter
                        for j, sent in enumerate(sentences, start=1):
                            insert_unit(child["kind"], f"{label or u['kind']}-{j}", f"{path}.{j:03d}", j, sent, {}, parent_id=unit_id)

        conn.commit()
    return {"ok": True}

# --- helper: safe int ---
def _to_int(x):
    try: return int(x)
    except: return None

@app.post("/jsonl/explode")
def jsonl_explode(body: dict):
    """
    Explode a JSONL 'panel.v2.6' file from corpus_jsonl into doc_unit rows.

    body = {
      "domain": "raising_arizona",
      "doc_key": "RaisingArizona_1987_panel_v2_6",
      "rules": {
        "path_prefix": "RA",
        "scene_gap_seconds": 45,
        "boundary_shot_regex": "^(INT\\.|EXT\\.|FADE|TITLE IS SUPERED)"
      }
    }
    """
    domain = body["domain"]
    doc_key = body["doc_key"]
    rules = body.get("rules", {})
    path_prefix = rules.get("path_prefix", "DOC")
    gap_sec = int(rules.get("scene_gap_seconds", 45))
    boundary_re = re.compile(rules.get("boundary_shot_regex", r"^\Z"))  # default no matches

    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        # 1) fetch raw JSONL text
        cur.execute(
            "SELECT payload FROM corpus_jsonl WHERE domain=%s AND doc_key=%s",
            (domain, doc_key)
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "corpus_jsonl not found"}

        payload = row["payload"]
        lines = [ln for ln in payload.splitlines() if ln.strip()]

        # 2) insertion helper
        def insert_unit(kind, label, path, ordinal, text, meta, parent_id=None):
            cur.execute("""
              INSERT INTO doc_unit (domain, doc_key, kind, label, path, ordinal, text, meta, parent_id)
              VALUES (%s,%s,%s,%s,%s::ltree,%s,%s,%s,%s)
              RETURNING id
            """, (domain, doc_key, kind, label, path, ordinal, text, Json(meta or {}), parent_id))
            return cur.fetchone()["id"]

        scene_idx = 0
        scene_id = None
        last_sub_secs = None
        act_counters = {}      # per scene
        sub_counters = {}      # per scene
        shot_counters = {}     # per scene

        def new_scene(meta_seed=None):
            nonlocal scene_idx, scene_id, last_sub_secs
            scene_idx += 1
            last_sub_secs = None
            act_counters[scene_idx] = 0
            sub_counters[scene_idx] = 0
            shot_counters[scene_idx] = 0
            scene_path = f"{path_prefix}.S{scene_idx:03d}"
            sid = insert_unit("scene", f"S{scene_idx:03d}", scene_path, scene_idx, None, meta_seed or {})
            return sid

        def get_scene_path():
            return f"{path_prefix}.S{scene_idx:03d}"

        # 3) pass through rows and emit units
        for raw in lines:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                # Skip malformed lines (or log)
                continue

            ptype = obj.get("panel_type")
            # bootstrap first scene if needed
            if scene_id is None:
                scene_id = new_scene({"bootstrap": True})

            # boundary by explicit scene (rare) or by shot text regex or by subtitle time gap
            boundary = False

            if ptype == "camera_shot":
                txt = (obj.get("text") or "").strip()
                if boundary_re.search(txt):
                    boundary = True

            if ptype == "subtitle":
                secs = obj.get("seconds_in")
                # Some rows may have seconds as string; coerce
                try:
                    secs = float(secs) if secs is not None else None
                except:
                    secs = None
                if last_sub_secs is not None and secs is not None:
                    if (secs - last_sub_secs) > gap_sec:
                        boundary = True
                if secs is not None:
                    last_sub_secs = secs

            if boundary:
                scene_id = new_scene({"boundary": True})

            scene_path = get_scene_path()

            if ptype == "camera_shot":
                shot_counters[scene_idx] += 1
                shot_no = shot_counters[scene_idx]
                shot_label = obj.get("shot_id") or f"shot_{shot_no:03d}"
                shot_path = f"{scene_path}.{shot_label}"
                meta = {
                    "page": obj.get("page"),
                    "shot_id": obj.get("shot_id"),
                    "text": obj.get("text")
                }
                insert_unit("shot", shot_label, shot_path, shot_no, obj.get("text"), meta, parent_id=scene_id)

            elif ptype == "scene_unit":
                act_counters[scene_idx] += 1
                k = act_counters[scene_idx]
                act_path = f"{scene_path}.act_{k:04d}"
                meta = {
                    "page": obj.get("page"),
                    "matched": obj.get("matched"),
                    "camera_shot": obj.get("camera_shot"),
                    "seconds_in": obj.get("seconds_in")
                }
                insert_unit("action", f"act_{k:04d}", act_path, k, obj.get("text"), meta, parent_id=scene_id)

            elif ptype == "subtitle":
                sub_counters[scene_idx] += 1
                k = sub_counters[scene_idx]
                sub_path = f"{scene_path}.sub_{k:04d}"
                meta = {
                    "time": obj.get("time"),
                    "seconds_in": obj.get("seconds_in"),
                    "camera_shot": obj.get("camera_shot"),
                    "subtitle_anchor": obj.get("subtitle_anchor")
                }
                insert_unit("subtitle", f"sub_{k:04d}", sub_path, k, obj.get("text"), meta, parent_id=scene_id)

            elif ptype == "scene":
                # If you ever include explicit scene rows, you can stuff synopsis/etc. here.
                # For now, treat as a soft boundary that's already handled by the regex/gap triggers.
                pass

            elif ptype == "meta":
                # ignore; could stash into doc-level meta later
                pass

            else:
                # unknown panel types ignored
                pass

        conn.commit()

    return {"ok": True, "scenes": scene_idx}

