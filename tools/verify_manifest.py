# -*- coding: utf-8 -*-
"""CI 门：核对某次运行的 manifest 与磁盘文件一致（T5 辨身的最小实现）。

用法：
  python tools/verify_manifest.py <run_dir> [--preset <preset.json>]

退出码：0 一致；1 不一致/缺文件/多文件；2 用法错误。

P1 修正（FC-007 / FC-008 / FC-006）：
  1) 双向遍历：清单里有而盘上没有 → FAIL；盘上有而清单里没有 → FAIL（旧版漏这一点）。
  2) 目录根指纹：对 (name, sha256) 排序求哈希，任何增删改都会变（旧版只比"当时目录里的文件"）。
  3) preset 内容哈希：可选 `--preset` 核对"跑的是哪份 preset"（旧版无从核对）。
  4) 可选执行者 HMAC 核对（PoC，需 AITB_SIGNING_KEY；不代表第三方签名）。

注意：本工具只能证明"字节没被改动"，**不能**证明"结论是对的"。
判决与证据的语义一致性（L1）需要另一层断言，见 EVIDENCE_REGISTRY_DESIGN.md。
"""
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

ALLOW_EXTRA = {"manifest.json"}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def root_of(files):
    return sha_obj([[k, files[k]] for k in sorted(files)])


def main(argv):
    run_dir = None
    preset_path = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--preset":
            if i + 1 >= len(argv):
                print("usage: verify_manifest.py <run_dir> [--preset <preset.json>]")
                return 2
            preset_path = argv[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            i += 1
            continue
        if run_dir is not None:
            print("usage: verify_manifest.py <run_dir> [--preset <preset.json>]")
            return 2
        run_dir = a
        i += 1
    if run_dir is None:
        print("usage: verify_manifest.py <run_dir> [--preset <preset.json>]")
        return 2
    d = Path(run_dir)
    mf = d / "manifest.json"
    if not mf.exists():
        print(f"FAIL manifest missing: {mf}")
        return 1
    m = json.loads(mf.read_text(encoding="utf-8"))
    files = m.get("files") or {}
    if len(files) < 4:
        print(f"FAIL manifest too thin: {sorted(files)}")
        return 1

    bad = []
    # 1) 清单 → 盘
    for name, h in files.items():
        p = d / name
        if not p.is_file():
            bad.append(f"{name}: missing")
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != h:
            bad.append(f"{name}: {got[:12]} != {h[:12]}")

    # 2) 盘 → 清单（旧版漏掉的单向）
    on_disk = {p.name for p in d.iterdir() if p.is_file()} - ALLOW_EXTRA
    extra = sorted(on_disk - set(files))
    if extra:
        bad.append(f"undeclared files on disk: {extra}")

    # 3) 目录根指纹：必须用**盘上实际字节**重算，而不是拿清单自己的值再算一遍
    #    （后者对"删条目 + 重算 root"的攻击无效）。root 覆盖盘上全部文件（除 manifest.json）。
    disk_hashes = {name: hashlib.sha256((d / name).read_bytes()).hexdigest()
                   for name in sorted(on_disk)}
    if "root" in m:
        if root_of(disk_hashes) != m["root"]:
            bad.append(f"root mismatch: disk {root_of(disk_hashes)[:12]} != manifest {str(m['root'])[:12]}")
    else:
        bad.append("root: absent (legacy manifest, cannot prove set completeness)")

    # 4) preset 内容哈希
    if preset_path:
        pj = json.loads(Path(preset_path).read_text(encoding="utf-8"))
        got = sha_obj({k: pj.get(k) for k in sorted(pj)})
        want = m.get("preset_sha256")
        if not want:
            bad.append("preset_sha256: absent in manifest")
        elif got != want:
            bad.append(f"preset_sha256: {got[:12]} != {str(want)[:12]}")

    # 5) 执行者 HMAC（PoC）
    key = os.environ.get("AITB_SIGNING_KEY")
    rj = d / "run.json"
    if key and rj.exists():
        meta = json.loads(rj.read_text(encoding="utf-8"))
        ex = meta.get("executor") or {}
        if ex.get("alg", "none") == "none":
            bad.append("executor: unsigned (alg=none)")
        else:
            body = {k: ex[k] for k in ("node", "user", "python")}
            want = hmac.new(key.encode("utf-8"), canonical(body), hashlib.sha256).hexdigest()
            if ex.get("hmac") != want:
                bad.append("executor: hmac mismatch")

    if bad:
        print("FAIL " + "; ".join(bad))
        return 1
    print(f"OK manifest verified (bidirectional, root={str(m.get('root'))[:16]}…): {sorted(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
