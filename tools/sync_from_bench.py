"""从开发目录（默认 ../bench，可用 AITB_SRC 指定）同步公开包所需的文件。

单一真源在 bench/；本脚本把它复制进 aitb_bench/，并在复制后做三项守卫：
  G1 公开包内不得出现本机绝对路径（盘符开头，如 D: 或 C: 后接反斜杠）
  G2 公开包内不得出现内部仓名与凭据探针关键字
  G3 core.py 与 vars.py 的 sha256 记录到 SYNC_STATE.json，供反查

用法：python tools/sync_from_bench.py [--check]
  --check 只比对，不写盘；不一致则退出码 1。
"""
import hashlib, json, os, re, shutil, sys
from pathlib import Path

PUB = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("AITB_SRC") or (PUB.parent / "bench")).resolve()
PKG = PUB / "aitb_bench"
STATE = PUB / "SYNC_STATE.json"

PAIRS = [
    (SRC / "bench.py", PKG / "core.py"),
    (SRC / "vars.py", PKG / "vars.py"),
    (SRC / "presets" / "selftest.json", PKG / "presets" / "selftest.json"),
]

FORBIDDEN_PATHS = re.compile(r"[CDEF]:\\\\")
FORBIDDEN_WORDS = ["channels", "send-audit", "126 SMTP", "github_pats", "ucvault", "lgd-work"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def scan(path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    hits = []
    if FORBIDDEN_PATHS.search(txt):
        hits.append("绝对路径")
    for w in FORBIDDEN_WORDS:
        if w in txt:
            hits.append(f"内部关键字 {w}")
    return hits


def main():
    check_only = "--check" in sys.argv
    bad, written = [], []
    for src, dst in PAIRS:
        if not src.exists():
            bad.append(f"缺源文件 {src}")
            continue
        if check_only:
            if not dst.exists() or sha(src) != sha(dst):
                bad.append(f"未同步 {dst.name}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.append(dst.name)
        hits = scan(dst if dst.exists() else src)
        if hits:
            bad.append(f"{dst.name}: {', '.join(hits)}")

    state = {p.name: sha(p) for p in PKG.glob("*.py")}
    state["presets"] = {p.name: sha(p) for p in (PKG / "presets").glob("*.json")}
    if not check_only:
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    if bad:
        print("SYNC: FAIL")
        for b in bad:
            print("  -", b)
        return 1
    print(f"SYNC: OK（{'校验' if check_only else '同步'} {len(PAIRS)} 个文件，守卫 G1/G2 通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
