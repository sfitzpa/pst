# api/motifs.py
import re, json
MOTIFS = ["setup","inversion","self_denigration","parallelism","contrast","admonition","consequence"]

def motifs_for(text:str, domain:str):
    t = text.lower().strip()
    seq = []
    if re.search(r"\b(but|yet|however)\b", t):
        seq.append("contrast")
    if re.search(r"\b(better .* than|do not|^do\b)\b", t):
        seq.append("admonition")
    if re.search(r"\btherefore|so that|leads to|reap\b", t):
        seq.append("consequence")
    if re.search(r"\bi (am|was|feel|guess|probably|maybe)\b", t) and re.search(r"(dumb|fool|idiot|stupid|pathetic)", t):
        seq.append("self_denigration")
    if re.search(r"(maybe|probably|turns out|then i realized)", t):
        seq.append("inversion")
    if re.search(r".+[,;:]\s*\w.+[,;:]\s*\w", t) or re.search(r"\b(wise|fool|righteous|wicked)\b.*\b(wise|fool|righteous|wicked)\b", t):
        seq.append("parallelism")
    if not seq or seq[0] != "setup":
        seq = ["setup"] + seq
    return seq[:3], {"domain": domain}