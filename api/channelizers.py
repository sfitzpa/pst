# channelizers.py
from typing import List, Tuple, Dict, Iterable
import re, hashlib, struct

EMB_DIM = 384

def _pad(xs: List[float], n=EMB_DIM) -> List[float]:
    return xs[:n] + [0.0] * max(0, n - len(xs))

# ----- rhetoric (384-d cheap heuristic) -----
def rhetoric_features(s: str) -> List[float]:
    t = s.lower()
    feats = [
        1.0 if re.search(r"\b(but|yet|however)\b", t) else 0.0,   # contrast
        1.0 if re.search(r"\b(so|therefore|thus)\b", t) else 0.0, # causal
        1.0 if re.search(r"\bif\b", t) else 0.0,                  # conditional
        1.0 if re.search(r"\b(no|not|never|none)\b", t) else 0.0, # negation
        1.0 if re.match(r"^[a-z]+(?:\s+[a-z]+){0,2}\b", t) and t.endswith("!") else 0.0,  # imperative-ish
        1.0 if "?" in t else 0.0,                                 # question
        1.0 if re.search(r"\bi\b", t) and re.search(r"\byou\b", t) else 0.0, # pronoun mix
        min(1.0, t.count(",")/3.0),
        min(1.0, sum(c in ";:" for c in t)/2.0),
        min(1.0, sum(c in "'\"" for c in t)/2.0),
        min(1.0, len(t)/160.0),
        1.0 if re.search(r"\b(and|or)\b.*\b(and|or)\b", t) else 0.0
    ]
    return _pad(feats)

# ----- imagery (normalize buckets → 384-d) -----
IMAGERY_BUCKETS = {
    "light":  ["light","shine","bright","candle","lamp","sun"],
    "dark":   ["dark","shadow","night","gloom","dim","fog"],
    "body":   ["hand","heart","mouth","eyes","foot","back","bone"],
    "nature": ["river","tree","seed","harvest","wind","stone","mountain"],
    "money":  ["gold","silver","coin","wealth","poor","debt","price"],
    "family": ["father","mother","son","daughter","friend","neighbor"],
}
def imagery_features(s: str) -> List[float]:
    t, vec = s.lower(), []
    for _, words in IMAGERY_BUCKETS.items():
        vec.append(sum(t.count(w) for w in words))
    norm = (sum(x*x for x in vec) ** 0.5) or 1.0
    vec = [x / norm for x in vec]
    return _pad(vec)

# ----- lexico-semantic (stable 384-d from hash) -----
def lexico_semantic(s: str) -> List[float]:
    h = hashlib.blake2b(s.encode("utf-8"), digest_size=64).digest()
    vals: List[float] = []
    while len(vals) < EMB_DIM:
        for i in range(0, len(h), 8):
            vals.append(abs(struct.unpack(">q", h[i:i+8])[0]) % 10_000 / 10_000.0)
            if len(vals) == EMB_DIM: break
        h = hashlib.blake2b(h, digest_size=64).digest()
    return vals

# ----- registry + runner -----
CHANNELIZERS = {
    "rhetoric": rhetoric_features,
    "imagery": imagery_features,
    "lexico_semantic": lexico_semantic,
}

def run_channels(text: str, chosen: Iterable[str] | None = None) -> Dict[str, List[float]]:
    active = CHANNELIZERS if chosen is None else {c: CHANNELIZERS[c] for c in chosen if c in CHANNELIZERS}
    return {ch: fn(text) for ch, fn in active.items()}
