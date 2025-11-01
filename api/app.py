from fastapi import FastAPI
import os, math
from datetime import datetime, timedelta
import json

from fastapi import Body
from fastapi.middleware.cors import CORSMiddleware

# app.py (snippets)
from .routes.xml_process_corpus import router as corpus_router
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from psycopg.types.json import Json
import re, psycopg
from psycopg.rows import dict_row
from collections import defaultdict
from lxml import etree

from api.services.move_ingest import default_session_id, ingest_one_text, sentence_split

app = FastAPI()
app.include_router(corpus_router)

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

class IngestBody(BaseModel):
    domain: str
    session_id: Optional[str] = None
    text: str
    channels: Optional[List[str]] = None  # None → all registered channels

@app.post("/ingest_text")
def ingest_text(body: IngestBody):
    sents = sentence_split(body.text)
    if not sents:
        return {"ok": True, "sentences": 0, "channel": body.channel}

    session_id = body.session_id or default_session_id(body.domain)
    used_channels = None if (body.channel in (None, "", "all")) else [body.channel]

    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        prev_by_channel: Dict[str, int] = {}
        total_moves = 0
        total_edges = 0

        for i, sent in enumerate(sents):
            out = ingest_one_text(
                conn,
                sent,
                session_id=session_id,
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
        "session_id": session_id,
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

def build_path(
    scheme: str,
    *,
    ordinal: int,
    meta: dict,
    kind: str,
    label: Optional[str] = None,
) -> str:
    """Render an ltree path using the supplied format scheme.

    The format context exposes ``ordinal``, ``kind``, ``label`` and ``meta`` so
    callers can express paths such as ``H.{ordinal:03d}`` or
    ``PRV.{meta[chapter]}.{ordinal:02d}``.
    """
    return scheme.format(
        ordinal=ordinal,
        kind=kind,
        label=(label or ""),
        meta=meta,
    )

@app.post("/xml/explode")
def xml_explode(body: dict):
    domain = body["domain"]
    doc_key = body["doc_key"]
    rules = body.get("rules", {})
    unit_rules = rules.get("units") or []

    if not unit_rules:
        return {"ok": False, "error": "rules.units is required"}

    namespaces = rules.get("namespaces") or None
    root_path = rules.get("root_path", "/")
    default_path_scheme = rules.get("path_scheme")
    path_prefix_default = rules.get("path_prefix")
    clear_existing = rules.get("clear_existing", True)

    def _xpath(node, expr):
        return node.xpath(expr, namespaces=namespaces) if namespaces else node.xpath(expr)

    def _coerce_value(val):
        if val is None:
            return None
        if isinstance(val, etree._Element):
            text = val.text or ""
            return text.strip() or None
        if isinstance(val, bytes):
            return val.decode("utf-8").strip() or None
        text = str(val).strip()
        return text or None

    def _collect(node, expr):
        result = _xpath(node, expr)
        if isinstance(result, list):
            out = []
            for item in result:
                coerced = _coerce_value(item)
                if coerced:
                    out.append(coerced)
            return out
        coerced = _coerce_value(result)
        return [coerced] if coerced else []

    def _first(node, expr):
        vals = _collect(node, expr)
        return vals[0] if vals else None

    def _looks_like_xpath(expr: str) -> bool:
        return expr.startswith((
            "@",
            "./",
            "../",
            ".//",
            "//",
            "normalize-space",
            "string(",
            "concat(",
            "name(",
        ))

    def _resolve_meta(node, spec):
        meta = {}
        for key, expr in (spec or {}).items():
            val = None
            if isinstance(expr, str) and _looks_like_xpath(expr):
                val = _first(node, expr)
            elif callable(expr):
                val = expr(node)
            else:
                val = expr
            if val not in (None, ""):
                meta[key] = val
        return meta

    def _resolve_label(node, spec):
        if spec.get("label_path"):
            label = _first(node, spec["label_path"])
            if label:
                return label
        label_attr = spec.get("label_attr")
        if label_attr:
            attr = label_attr[1:] if label_attr.startswith("@") else label_attr
            label_val = node.get(attr)
            if label_val:
                label_val = label_val.strip()
                if label_val:
                    return label_val
        return None

    def _resolve_ordinal(node, spec, counters):
        ordinal_expr = spec.get("ordinal_path") or spec.get("ordinal")
        ordinal = None
        if ordinal_expr is not None:
            if isinstance(ordinal_expr, str) and _looks_like_xpath(ordinal_expr):
                ordinal = to_int(_first(node, ordinal_expr))
            else:
                ordinal = to_int(ordinal_expr)
        if ordinal is None:
            counters[spec["kind"]] += 1
            ordinal = counters[spec["kind"]]
        else:
            counters[spec["kind"]] = max(counters[spec["kind"]], ordinal)
        return ordinal

    def _resolve_text(node, spec):
        text_path = spec.get("text_path") or "normalize-space(.)"
        vals = _collect(node, text_path)
        if vals:
            return " ".join(vals)
        return None

    def _sanitize_token(token: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", token).strip("_")
        return cleaned or "unit"

    def _normalize_path(path: str) -> str:
        return ".".join(_sanitize_token(part) for part in path.split(".") if part)

    def _resolve_path(node, spec, ordinal, meta, kind, label):
        path = None
        path_scheme = spec.get("path_scheme") or default_path_scheme
        if path_scheme:
            try:
                path = build_path(
                    path_scheme,
                    ordinal=ordinal,
                    meta=meta,
                    kind=kind,
                    label=label,
                )
            except Exception:
                # fall back to defaults if formatting fails
                path = None

        if not path and spec.get("path_attr"):
            attr = spec["path_attr"]
            attr = attr[1:] if attr.startswith("@") else attr
            attr_val = node.get(attr)
            if attr_val:
                prefix = spec.get("path_prefix") or path_prefix_default
                token = _sanitize_token(attr_val)
                path = f"{prefix}.{token}" if prefix else token

        if not path:
            prefix = spec.get("path_prefix") or path_prefix_default or kind
            pad = int(spec.get("path_pad", 3))
            path = f"{prefix}.{ordinal:0{pad}d}" if prefix else f"{ordinal:0{pad}d}"

        return _normalize_path(path)

    with psycopg.connect(DB_URL, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, xml_payload FROM corpus_xml WHERE doc_key=%s AND domain=%s",
            (doc_key, domain),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "corpus_xml not found"}

        payload = row["xml_payload"]
        if isinstance(payload, str):
            xml_bytes = payload.encode("utf-8")
        elif isinstance(payload, memoryview):
            xml_bytes = payload.tobytes()
        else:
            xml_bytes = bytes(payload)

        try:
            xml_root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            return {"ok": False, "error": f"invalid xml: {exc}"}

        roots = _xpath(xml_root, root_path)
        if not roots:
            # allow the document root itself if the path resolves to the root
            if root_path in ("/", ".", "./"):
                roots = [xml_root]
            else:
                return {"ok": False, "error": f"root_path '{root_path}' yielded no nodes"}

        if clear_existing:
            cur.execute(
                "DELETE FROM doc_unit WHERE domain=%s AND doc_key=%s",
                (domain, doc_key),
            )

        counters = defaultdict(int)
        ids_by_node = {}
        kinds_by_node = {}
        inserted_by_kind = defaultdict(int)

        def insert_unit(kind, label, path, ordinal, text, meta, parent_id=None):
            cur.execute(
                """
                  INSERT INTO doc_unit (domain, doc_key, kind, label, path, ordinal, text, meta, parent_id)
                  VALUES (%s,%s,%s,%s,%s::ltree,%s,%s,%s,%s)
                  RETURNING id
                """,
                (domain, doc_key, kind, label, path, ordinal, text, Json(meta or {}), parent_id),
            )
            inserted_by_kind[kind] += 1
            return cur.fetchone()["id"]

        for root in roots:
            for spec in unit_rules:
                kind = spec["kind"]
                nodes = _xpath(root, spec["path"])
                for node in nodes:
                    label = _resolve_label(node, spec)
                    meta = _resolve_meta(node, spec.get("meta"))
                    ordinal = _resolve_ordinal(node, spec, counters)
                    text = _resolve_text(node, spec)
                    path = _resolve_path(node, spec, ordinal, meta, kind, label)

                    parent_id = None
                    if spec.get("parent_xpath"):
                        for candidate in _xpath(node, spec["parent_xpath"]):
                            parent_id = ids_by_node.get(candidate)
                            if parent_id:
                                break
                    if parent_id is None and spec.get("parent_kind"):
                        parent_kinds = spec["parent_kind"]
                        if isinstance(parent_kinds, str):
                            parent_kinds = [parent_kinds]
                        for ancestor in node.iterancestors():
                            anc_id = ids_by_node.get(ancestor)
                            if anc_id and kinds_by_node.get(ancestor) in parent_kinds:
                                parent_id = anc_id
                                break
                    if parent_id is None and spec.get("inherit_parent"):
                        ancestor = next(iter(node.iterancestors()), None)
                        if ancestor is not None:
                            parent_id = ids_by_node.get(ancestor)

                    unit_id = insert_unit(kind, label, path, ordinal, text, meta, parent_id)
                    ids_by_node[node] = unit_id
                    kinds_by_node[node] = kind

                    if spec.get("children"):
                        for child in spec["children"]:
                            if child.get("split") == "sentence" and text:
                                sentences = sentence_split(text)
                                for j, sent in enumerate(sentences, start=1):
                                    child_path = f"{path}.{j:03d}"
                                    insert_unit(
                                        child["kind"],
                                        f"{label or kind}-{j}",
                                        _normalize_path(child_path),
                                        j,
                                        sent,
                                        {},
                                        parent_id=unit_id,
                                    )

        conn.commit()

    total = sum(inserted_by_kind.values())
    return {"ok": True, "inserted": total, "by_kind": dict(inserted_by_kind)}

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
