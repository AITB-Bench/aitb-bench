# -*- coding: utf-8 -*-
"""CI 门：核对某次运行的 manifest 与磁盘文件一致（T5 辨身的最小实现）。

用法：python tools/verify_manifest.py runs/<ts>_demo
退出码：0 一致；1 不一致或缺文件。
"""
import hashlib
import json
import sys
from pathlib import Path


def main(argv):
    if len(argv) != 2:
        print("usage: verify_manifest.py <run_dir>")
        return 2
    d = Path(argv[1])
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    files = m["files"]
    if len(files) < 4:
        print(f"FAIL manifest too thin: {sorted(files)}")
        return 1
    bad = []
    for name, h in files.items():
        p = d / name
        if not p.exists():
            bad.append(f"{name}: missing")
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != h:
            bad.append(f"{name}: {got[:12]} != {h[:12]}")
    if bad:
        print("FAIL " + "; ".join(bad))
        return 1
    print(f"OK manifest verified: {sorted(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
