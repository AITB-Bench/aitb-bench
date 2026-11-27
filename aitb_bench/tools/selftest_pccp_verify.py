# -*- coding: utf-8 -*-
"""pccp_verify.py 的反照自测：没有真实数据集也要证明它会红。

四步：
 1. 造一个小集合（2 文件）→ dir 必须 OK
 2. 改一个字节 → dir 必须 FAIL（否则它只是装饰）
 3. 打包成 zip（含 MANIFEST/ROOT）→ zip 必须 OK；去掉 MANIFEST 重打 → 必须 FAIL
 4. --break 反照 → 必须 OK
"""
import hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "pccp_verify.py"
EXPECT_OK, results = None, []


def run(*args):
    p = subprocess.run([sys.executable, str(TOOL)] + list(args), capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def pai(hs):
    while len(hs) > 1:
        hs = [hashlib.sha256(hs[i] + (hs[i + 1] if i + 1 < len(hs) else hs[i])).digest()
              for i in range(0, len(hs), 2)]
    return hs[0].hex()


def note(name, ok, detail=""):
    results.append(ok)
    print(("  PASS  " if ok else "  FAIL  ") + name + ("  (" + detail.strip().splitlines()[-1] + ")" if detail else ""))


d = Path(tempfile.mkdtemp(prefix="pccp_fx_"))
try:
    (d / "dataset").mkdir()
    (d / "dataset" / "a.md").write_text("go: case A\n", encoding="utf-8")
    (d / "dataset" / "b.json").write_text(json.dumps({"case": "B"}), encoding="utf-8")
    rows = []
    for p in ("dataset/a.md", "dataset/b.json"):
        b = (d / p).read_bytes()
        rows.append({"path": p, "archive_path": p, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)})
    root = pai([bytes.fromhex(r["sha256"]) for _, r in sorted((r["path"], r) for r in rows)])
    EXPECT_OK = root
    (d / "MANIFEST.json").write_text(json.dumps({"dataset": "PCCP-Bench", "version": "0.1.0",
                                                 "leaf_count": len(rows), "merkle_root": root,
                                                 "files": rows}, ensure_ascii=False), encoding="utf-8")
    (d / "ROOT.txt").write_text("PCCP-Bench v0.1.0\nMERKLE_ROOT %s\nLEAVES %d\n" % (root, len(rows)), encoding="utf-8")
    (d / "standing_entry.json").write_text(json.dumps({"version": "0.1.0", "doi": None, "license": "UNSET"}),
                                           encoding="utf-8")
    (d / "CITATION.cff").write_text("version: 0.1.0\nlicense: null\n", encoding="utf-8")

    rc, out = run("dir", "--dir", str(d), "--expect", root)
    note("干净集合 → dir OK", rc == 0 and "ROOT: OK" in out, out)

    z = d / "pccp-bench_zenodo_v0.1.0.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            zf.write(d / r["archive_path"], r["archive_path"])
        zf.write(d / "MANIFEST.json", "MANIFEST.json")
        zf.write(d / "ROOT.txt", "ROOT.txt")
    rc, out = run("zip", "--zip", str(z), "--expect", root)
    note("含 MANIFEST 的包 → zip OK", rc == 0 and "ARCHIVE: OK" in out, out)

    # 去掉 MANIFEST 重打
    z2 = d / "no_manifest.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        for r in rows:
            zf.write(d / r["archive_path"], r["archive_path"])
    rc, out = run("zip", "--zip", str(z2), "--expect", root)
    note("缺 MANIFEST 的包 → 必须 FAIL", rc == 1 and "包里没有 MANIFEST.json" in out, out)

    # 改一个字节
    (d / "dataset" / "a.md").write_text("go: case A!\n", encoding="utf-8")
    rc, out = run("dir", "--dir", str(d), "--expect", root)
    note("改一字节 → 必须 FAIL", rc == 1 and "MISMATCH" in out, out)
    (d / "dataset" / "a.md").write_text("go: case A\n", encoding="utf-8")

    rc, out = run("dir", "--dir", str(d), "--expect", root, "--break")
    note("--break 反照 → OK", rc == 0 and "NEGATIVE-CONTROL: OK" in out, out)

    rc, out = run("versions", "--dir", str(d), "--expect", "0.1.0")
    note("版本四处同号", rc == 0 and "VERSIONS: OK" in out, out)
    rc, out = run("license", "--dir", str(d))
    note("许可未定 → 必须红", rc == 1 and "LICENSE: UNSET" in out, out)
    (d / "dataset" / "claim.md").write_text("见 doi 10.5281/zenodo.1234567\n", encoding="utf-8")
    rc, out = run("claims", "--dir", str(d))
    note("无 DOI 却写 DOI → 必须红", rc == 1 and "DOI-WITHOUT-RECORD" in out, out)
    rc, out = run("dir", "--dir", str(d / "nope"), "--expect", root)
    note("目录不在 → BLOCKED(2) 而非 PASS", rc == 2 and "BLOCKED" in out, out)
finally:
    shutil.rmtree(d, ignore_errors=True)

print("\n结果：%d 通过 / %d 失败" % (sum(results), len(results) - sum(results)))
sys.exit(0 if all(results) else 1)
