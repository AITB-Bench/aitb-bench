# -*- coding: utf-8 -*-
"""本地变量：运行期从 config.local.json 读；仓里只放 config.example.json。"""
import json
import re
from pathlib import Path

BENCH = Path(__file__).resolve().parent
CFG = BENCH / "config.local.json"
EX = BENCH / "config.example.json"
PAT = re.compile(r"\${([A-Za-z0-9_]+)}")


def load_vars():
    p = CFG if CFG.exists() else EX
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("vars", {})


def expand(obj, v=None):
    v = load_vars() if v is None else v
    if isinstance(obj, str):
        def rep(m):
            k = m.group(1)
            return str(v.get(k, m.group(0)))
        return PAT.sub(rep, obj)
    if isinstance(obj, list):
        return [expand(x, v) for x in obj]
    if isinstance(obj, dict):
        return {k: expand(x, v) for k, x in obj.items()}
    return obj
