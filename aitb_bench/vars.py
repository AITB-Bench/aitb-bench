# -*- coding: utf-8 -*-
"""本地变量：运行期从 config.local.json 读；同名环境变量作为兜底；仓里只放 config.example.json。"""
import json
import os
import re
from pathlib import Path

BENCH = Path(__file__).resolve().parent
CFG = BENCH / "config.local.json"
EX = BENCH / "config.example.json"
PAT = re.compile(r"\${([A-Za-z0-9_]+)}")
_WARNED = set()


def load_vars():
    v = {}
    p = CFG if CFG.exists() else EX
    if p.exists():
        v = dict(json.loads(p.read_text(encoding="utf-8")).get("vars", {}) or {})
    # 配置文件优先；未声明的名字再查环境变量（README 里承诺 ${AITB_RUNS} 这类写法可用）
    for k, val in os.environ.items():
        v.setdefault(k, val)
    return v


def expand(obj, v=None):
    v = load_vars() if v is None else v
    if isinstance(obj, str):
        def rep(m):
            k = m.group(1)
            if k in v:
                return str(v[k])
            # 不静默置空：保留占位符并警告一次，否则预设会带着空串继续跑
            if k not in _WARNED:
                _WARNED.add(k)
                print(f"[warn] 变量 {k} 未定义，保留 ${{{k}}} 占位符")
            return m.group(0)
        return PAT.sub(rep, obj)
    if isinstance(obj, list):
        return [expand(x, v) for x in obj]
    if isinstance(obj, dict):
        return {k: expand(x, v) for k, x in obj.items()}
    return obj
