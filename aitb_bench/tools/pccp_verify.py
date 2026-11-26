# -*- coding: utf-8 -*-
"""PCCP-Bench 的冻结校验（试真台 AITB 的检查器，纯标准库、零依赖）。

它只回答一个问题：**此刻这套字节，还是不是 2d305387… 那一批？**

规则必须与冻结时的实现逐字一致（这是 2026-11-26 实测出来的，不是抄来的）：
  leaf = 文件 sha256 摘要的**字节**（不再拿 path 二次哈希）
  files 按 path 排序 → 成对 sha256(a+b) → 奇数节点与自身配对
反过来写成 sha256(path + NUL + 摘要) 也能算出一个根，但会得到 662ba5a7…，与冻结值差得远。
错规则的危害：外人照做会算出另一个根，然后以为包被改过。所以这里写死实测值并注释来源。

子命令
------
  dir     --dir D --expect ROOT       校验目录（按 archive_path 找文件）
  zip     --zip Z --expect ROOT       校验包（要求包内有 MANIFEST.json 与 ROOT.txt）
  versions --dir D --expect 0.1.0     版本四处同号（entry / manifest / CITATION / ROOT.txt）
  license --dir D                     许可是否已定（UNSET 就是未定，不粉饰）
  claims  --dir D                     文本里有没有 DOI 主张，而记录里并无 DOI
  --break                             反照（T1）：先弄坏一个字节再算，**必须**算出不一致

退出码：0 守住；1 失守（校验不符）；2 环境缺失（目录/文件不在 → 应记为 BLOCKED，不是 PASS）。
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def pai(hs):
    hs = list(hs)
    if not hs:
        return None
    while len(hs) > 1:
        hs = [hashlib.sha256(hs[i] + (hs[i + 1] if i + 1 < len(hs) else hs[i])).digest()
              for i in range(0, len(hs), 2)]
    return hs[0].hex()


def rows_of(man):
    return man.get("files") or man.get("leaves") or []


def check_dir(d):
    man = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    bad, good, sizes = [], [], 0
    for e in rows_of(man):
        p = d / (e.get("archive_path") or e["path"])
        if not p.is_file():
            p = d / e["path"]
        if not p.is_file():
            bad.append((e.get("archive_path") or e["path"], "缺失"))
            continue
        blob = p.read_bytes()
        if hashlib.sha256(blob).hexdigest() != e["sha256"]:
            bad.append((p.as_posix(), "摘要不符"))
            continue
        good.append((e["path"], e["sha256"]))
        sizes += len(blob)
    return man, good, bad, sizes


def cmd_dir(a):
    d = Path(a.dir)
    if not (d / "MANIFEST.json").is_file():
        print("BLOCKED: %s 下没有 MANIFEST.json（这台机器上没有这套字节）" % d)
        return 2
    man, good, bad, sizes = check_dir(d)
    print("LEAVES: %d/%s  BYTES: %d" % (len(good), man.get("leaf_count"), sizes))
    if bad:
        print("BYTES: MISMATCH %r" % (bad[:4],))
        return 1
    print("BYTES: OK %d/%d" % (len(good), len(good)))
    hr = pai([bytes.fromhex(s) for _, s in sorted(good)])
    if a.break_:
        # 反照：把第一个叶子改一个字节，根必须变。根不变 = 这道检查只是装饰。
        tmp = Path(tempfile.mkdtemp(prefix="pccp_break_"))
        try:
            first = rows_of(man)[0]
            src = d / (first.get("archive_path") or first["path"])
            if not src.is_file():
                src = d / first["path"]
            dst = tmp / "x.bin"
            blob = bytearray(src.read_bytes())
            blob[0] = blob[0] ^ 0xFF if blob else 0x00
            dst.write_bytes(bytes(blob))
            broken = hashlib.sha256(dst.read_bytes()).hexdigest()
            good2 = [(p, broken if p == first["path"] else s) for p, s in good]
            hr2 = pai([bytes.fromhex(s) for _, s in sorted(good2)])
            print("BREAK: %s → %s" % (hr[:12], hr2[:12]))
            if hr2 != hr:
                print("NEGATIVE-CONTROL: OK 改一字节根就变，这道检查会失败")
                return 0
            print("NEGATIVE-CONTROL: FAIL 改了字节根却不变——这道检查抓不到改动")
            return 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("ROOT: %s" % hr)
    if a.expect and hr != a.expect:
        print("ROOT: MISMATCH %s != %s" % (hr, a.expect))
        return 1
    print("ROOT: OK")
    return 0


def cmd_zip(a):
    z = Path(a.zip)
    if not z.is_file():
        print("BLOCKED: 包不在 %s" % z)
        return 2
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        if a.break_:
            tmp = Path(tempfile.mkdtemp(prefix="pccp_zb_"))
            try:
                data = {n: zf.read(n) for n in names}
                key = next(n for n in names if n.endswith(".md") or n.endswith(".json"))
                b = bytearray(data[key])
                b[0] = b[0] ^ 0xFF if b else 0
                data[key] = bytes(b)
                out = tmp / "broken.zip"
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
                    for n, blob in data.items():
                        w.writestr(n, blob)
                got = _zip_root(out)
                got2 = _zip_root(z)
                print("BREAK: 原 %s → 坏 %s" % (got2[:12], got[:12]))
                if got != got2:
                    print("NEGATIVE-CONTROL: OK 改一字节根就变")
                    return 0
                print("NEGATIVE-CONTROL: FAIL 改了字节根却不变")
                return 1
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        for must in ("MANIFEST.json", "ROOT.txt"):
            if must not in names:
                print("ARCHIVE: FAIL 包里没有 %s —— 外人拿到包无法复算" % must)
                return 1
        man = json.loads(zf.read("MANIFEST.json"))
        bad = []
        for e in rows_of(man):
            ap = e.get("archive_path")
            if not ap or ap not in names:
                bad.append((e["path"], "包内无对应路径"))
                continue
            if hashlib.sha256(zf.read(ap)).hexdigest() != e["sha256"]:
                bad.append((ap, "包内摘要不符"))
    if bad:
        print("ARCHIVE: FAIL %r" % (bad[:4],))
        return 1
    hr = _zip_root(z)
    print("ARCHIVE: OK %d 条目 / %d 叶子 / 根 %s" % (len(names), len(rows_of(man)), hr))
    if a.expect and hr != a.expect:
        print("ARCHIVE: FAIL 复算根 %s != %s" % (hr, a.expect))
        return 1
    return 0


def _zip_root(z):
    with zipfile.ZipFile(z) as zf:
        man = json.loads(zf.read("MANIFEST.json"))
        rows = rows_of(man)
        return pai([bytes.fromhex(e["sha256"]) for _, e in sorted((e["path"], e) for e in rows)])


def cmd_versions(a):
    d = Path(a.dir)
    if not (d / "ROOT.txt").is_file():
        print("BLOCKED: 没有 ROOT.txt")
        return 2
    seen = {}
    ent = d / "standing_entry.json"
    if ent.is_file():
        seen["entry"] = json.loads(ent.read_text(encoding="utf-8")).get("version")
    man = d / "MANIFEST.json"
    if man.is_file():
        seen["manifest"] = json.loads(man.read_text(encoding="utf-8")).get("version")
    cif = d / "CITATION.cff"
    if cif.is_file():
        m = re.search(r"^version:\s*(\S+)", cif.read_text(encoding="utf-8"), re.M)
        seen["citation"] = m.group(1).strip('"') if m else None
    m = re.search(r"v?(\d+\.\d+\.\d+)", (d / "ROOT.txt").read_text(encoding="utf-8"))
    seen["ROOT.txt"] = m.group(1) if m else None
    print("VERSIONS: %r" % (seen,))
    vals = {v for v in seen.values() if v}
    if len(vals) != 1 or (a.expect and vals != {a.expect}):
        print("VERSIONS: MISMATCH")
        return 1
    print("VERSIONS: OK %s" % vals.pop())
    return 0


def cmd_license(a):
    d = Path(a.dir)
    ent = d / "standing_entry.json"
    cand = []
    if ent.is_file():
        cand.append(json.loads(ent.read_text(encoding="utf-8")).get("license"))
    cif = d / "CITATION.cff"
    if cif.is_file():
        m = re.search(r"^license:\s*(\S+)", cif.read_text(encoding="utf-8"), re.M)
        cand.append(None if not m or m.group(1).strip('"') in ("null", "~") else m.group(1).strip('"'))
    if not cand:
        print("BLOCKED: 找不到 standing_entry.json / CITATION.cff")
        return 2
    if all(c in (None, "", "UNSET") for c in cand):
        print("LICENSE: UNSET 许可未定 —— 根可算，包不可发")
        return 1
    print("LICENSE: SET %r" % (cand,))
    return 0


def cmd_claims(a):
    d = Path(a.dir)
    ent = d / "standing_entry.json"
    has_doi = bool(ent.is_file() and json.loads(ent.read_text(encoding="utf-8")).get("doi"))
    hits = []
    for p in d.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".md", ".cff", ".json", ".txt", ".html"):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"10\.5281/zenodo\.[0-9]+", t):
            hits.append((p.name, m.group(0)))
    if hits and not has_doi:
        print("CLAIMS: DOI-WITHOUT-RECORD %r —— 文本里写了 DOI，记录里没有" % (hits[:3],))
        return 1
    print("CLAIMS: CLEAN（%d 处 DOI 字样）" % len(hits))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dir", "zip", "versions", "license", "claims"])
    ap.add_argument("--dir")
    ap.add_argument("--zip")
    ap.add_argument("--expect")
    ap.add_argument("--break", dest="break_", action="store_true")
    a = ap.parse_args()
    table = {"dir": cmd_dir, "zip": cmd_zip, "versions": cmd_versions,
             "license": cmd_license, "claims": cmd_claims}
    return table[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
