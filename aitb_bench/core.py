# -*- coding: utf-8 -*-
"""bench.py — 复用型验收台：清单驱动、适配器执行、每次运行产出证据包。

形态取自业界 conformance harness 的通行做法：
  清单(preset) → 逐项检查(adapter) → 每次运行一个证据目录(run.json / verdicts.json / manifest.json)
  → 人读报告(report.md) + 可视化(snapshot.html) → 退出码非零即失败。
零依赖、纯标准库、不联网除显式 http 检查。
"""
import argparse, hashlib, html, json, os, platform, shutil, subprocess, sys, time
from pathlib import Path

BENCH = Path(__file__).resolve().parent


def _presets_dirs():
    """预设搜索路径：$AITB_PRESETS 与包内 presets **并存**（不是替换），再退到 cwd/presets。"""
    dirs = []
    env = os.environ.get("AITB_PRESETS")
    if env and Path(env).is_dir():
        dirs.append(Path(env))
    elif env:
        print(f"[warn] AITB_PRESETS={env} 不是目录，已忽略（内置预设仍在）")
    here = BENCH / "presets"
    if here.is_dir():
        dirs.append(here)
    cwd = Path.cwd() / "presets"
    if cwd.is_dir() and cwd not in dirs:
        dirs.append(cwd)
    return dirs


def find_preset(name):
    for d in PRESETS_DIRS:
        p = d / f"{name}.json"
        if p.exists():
            return p
    searched = ", ".join(str(d) for d in PRESETS_DIRS)
    raise FileNotFoundError(f"找不到 preset {name!r}（已找：{searched}）")


def _runs_dir():
    """$AITB_RUNS > 仓库内 runs（开发态）> 当前工作目录 runs（安装态，避免写进 site-packages）。"""
    env = os.environ.get("AITB_RUNS")
    if env:
        return Path(env)
    repo = (BENCH / ".git").exists() or (BENCH.parent / ".git").exists()
    base = (BENCH / "runs") if repo else (Path.cwd() / "runs")
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        return Path.cwd() / "runs"


PRESETS_DIRS = _presets_dirs()
PRESETS = PRESETS_DIRS[0] if PRESETS_DIRS else Path.cwd() / "presets"
RUNS = _runs_dir()
VERDICTS = ("PASS", "FAIL", "SKIP", "BLOCKED")


def sha256_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def run_cmd(cmd, cwd=None, timeout=300, env=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           shell=isinstance(cmd, str), env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or ""), int((time.time() - t0) * 1000)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out + f"\n[timeout after {timeout}s]", int((time.time() - t0) * 1000)
    except Exception as e:
        return 125, f"[exception] {e}", int((time.time() - t0) * 1000)


# ---------------- adapters ----------------

def a_cmd(spec, ctx):
    """跑一条命令，按 expect 子串判定。"""
    cwd = (BENCH / spec["cwd"]).resolve() if spec.get("cwd") else BENCH
    cmd = spec["cmd"]
    rc, out, ms = run_cmd(cmd, cwd=cwd, timeout=spec.get("timeout", 300))
    expect = spec.get("expect")
    tail = "\n".join([l for l in out.strip().splitlines() if l.strip()][-3:])
    if rc == 124:
        return "BLOCKED", f"超时 {spec.get('timeout', 300)}s", tail, ms
    if expect and expect not in out:
        return "FAIL", f"未出现期望串：{expect!r}（rc={rc}）", tail, ms
    if not expect and rc != 0:
        return "FAIL", f"rc={rc}", tail, ms
    return "PASS", (f"含期望串 {expect!r}" if expect else f"rc=0"), tail, ms


def a_files(spec, ctx):
    """核对文件在场与大小下限。base 可为绝对路径，path 相对 base。"""
    miss = []
    base = Path(spec["base"]) if spec.get("base") else BENCH
    for item in spec["paths"]:
        p = Path(item["path"])
        if not p.is_absolute():
            p = base / p
        if not p.exists():
            miss.append(f"缺 {p}")
        elif p.stat().st_size < item.get("min_size", 1):
            miss.append(f"{p.name} 仅 {p.stat().st_size} B（需 ≥{item.get('min_size', 1)}）")
    if miss:
        return "FAIL", "; ".join(miss), "", 0
    return "PASS", f"{len(spec['paths'])} 个文件在场", "", 0


def a_http(spec, ctx):
    """HTTP 探测；预期状态码不符即 FAIL，超时记 BLOCKED（不折算 PASS）。"""
    import urllib.request, urllib.error
    out = []
    ms0 = time.time()
    ok = True
    for t in spec["targets"]:
        url = t["url"]
        want = t.get("expect", 200)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bench/1.0"})
            with urllib.request.urlopen(req, timeout=t.get("timeout", 20)) as r:
                code = r.getcode()
                body_head = r.read(256)
        except urllib.error.HTTPError as e:
            code = e.code
            body_head = b""
        except Exception as e:
            out.append(f"{url} -> BLOCKED {type(e).__name__}")
            ok = False
            continue
        mark = "ok" if code == want else f"want {want}"
        if code != want:
            ok = False
        out.append(f"{url} -> {code} ({mark})")
    return ("PASS" if ok else "FAIL"), "; ".join(out), "", int((time.time() - ms0) * 1000)


def a_pyver(spec, ctx):
    """环境矩阵：对每个可用的解释器跑同一条命令；缺的记 SKIP，坏的不许冒充缺席。"""
    cand = spec.get("interpreters") or ["python", "python3", "py -3", "py -3.11", "py -3.12"]
    rows, ok, tried, blocked = [], True, 0, 0
    absent_marks = ("not installed", "requested python version", "can't open", "cannot open",
                    "未安装", "no installed", "not found", "no suitable python runtime")
    for it in cand:
        rc, out, ms = run_cmd(f"{it} -c \"import sys;print(sys.version.split()[0])\"", cwd=BENCH, timeout=30)
        if rc == 124:
            blocked += 1
            rows.append(f"{it}: BLOCKED（版本探测超时）")
            continue
        if rc != 0:
            low = (out or "").lower()
            looks_absent = any(m.lower() in low for m in absent_marks)
            exe = it.split()[0]
            if shutil.which(exe) and not looks_absent:
                # 在场但不可用（损坏 / 被权限拦住）：这是 BLOCKED——没测到，不等于测失败
                blocked += 1
                rows.append(f"{it}: BLOCKED（在场但不可执行：{out.strip().splitlines()[-1][:60] if out.strip() else 'unknown'}）")
            else:
                rows.append(f"{it}: 不在场")
            continue
        tried += 1
        ver = out.strip().splitlines()[-1] if out.strip() else "?"
        rc2, out2, ms2 = run_cmd(f"{it} {spec['script']}", cwd=(BENCH / spec["cwd"]).resolve(),
                                 timeout=spec.get("timeout", 300))
        if rc2 == 124:
            blocked += 1
            rows.append(f"{it} ({ver}): BLOCKED（执行超时）")
            continue
        good = rc2 == 0 and (spec.get("expect") in out2 if spec.get("expect") else True)
        rows.append(f"{it} ({ver}): {'ok' if good else 'FAIL'}")
        ok = ok and good
    if tried == 0 and blocked == 0:
        return "SKIP", "无任何解释器可用", "; ".join(rows), 0
    if blocked:
        return "BLOCKED", f"{blocked} 个解释器无法判定（超时或不可执行）", "; ".join(rows), 0
    return ("PASS" if ok else "FAIL"), f"{tried} 个解释器跑通", "; ".join(rows), 0


ADAPTERS = {"cmd": a_cmd, "files": a_files, "http": a_http, "pyver": a_pyver}


# ---------------- runner ----------------

def _vars():
    try:
        import vars as _v
        return _v
    except Exception:
        pass
    try:
        from .vars import expand
        class _M:
            pass
        m = _M()
        m.expand = expand
        return m
    except Exception:
        return None


def load_preset(name):
    p = find_preset(name)
    preset = json.loads(p.read_text(encoding="utf-8"))
    v = _vars()
    if v is not None:
        try:
            preset = v.expand(preset)
        except Exception as e:
            print(f"[warn] 变量展开失败：{e}")
    return preset


def execute(preset, offline=False, strict=False):
    run_id = time.strftime("%Y%m%dT%H%M%S")
    rdir = RUNS / f"{run_id}_{preset['name']}"
    rdir.mkdir(parents=True, exist_ok=True)
    ctx = {"offline": offline}
    verdicts = []
    for spec in preset["checks"]:
        if offline and spec.get("needs_network"):
            verdicts.append({"id": spec["id"], "type": spec["type"], "status": "SKIP",
                             "why": "offline 模式跳过联网检查", "evidence": "", "ms": 0})
            continue
        fn = ADAPTERS.get(spec["type"])
        if fn is None:
            verdicts.append({"id": spec["id"], "type": spec["type"], "status": "BLOCKED",
                             "why": f"未知适配器 {spec['type']}", "evidence": "", "ms": 0})
            continue
        t0 = time.time()
        status, why, evidence, ms = fn(spec, ctx)
        want = spec.get("expect_status", "PASS")
        neg = want == "FAIL"  # 负控：这条检查被要求必须失败，它为 FAIL 是"按设计变红"
        if status != want:
            why = f"反预期：期望 {want}，实得 {status}（{why}）"
            status = "FAIL"
        verdicts.append({"id": spec["id"], "type": spec["type"], "status": status,
                         "why": why, "evidence": evidence, "ms": ms or int((time.time() - t0) * 1000),
                         "negative_control": neg})
        print(f"[{status:<7}]{'[NEG-CTRL]' if neg else '          '} {spec['id']:<38} {why}")

    counts = {k: sum(1 for v in verdicts if v["status"] == k) for k in VERDICTS}
    run_meta = {
        "run_id": run_id, "preset": preset["name"], "title": preset.get("title", preset["name"]),
        "started_at": run_id, "host": platform.node(), "os": platform.platform(),
        "python": sys.version.split()[0], "counts": counts, "strict": strict,
    }
    (rdir / "run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "verdicts.json").write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")

    report = render_report(preset, verdicts, counts)
    (rdir / "report.md").write_text(report, encoding="utf-8")
    (rdir / "snapshot.html").write_text(render_html(preset, verdicts, counts, run_meta), encoding="utf-8")

    manifest = {"run_id": run_id, "files": {}}
    for f in sorted(rdir.iterdir()):
        if f.name != "manifest.json":
            manifest["files"][f.name] = sha256_file(f)
    (rdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    # latest 指针
    link = RUNS / "latest"
    if link.exists() or link.is_symlink():
        try:
            link.unlink()
        except Exception:
            shutil.rmtree(link, ignore_errors=True)
    try:
        link.symlink_to(rdir.name, target_is_directory=True)
    except Exception:
        (RUNS / "latest.txt").write_text(rdir.name, encoding="utf-8")

    print(f"\n{counts}  ->  {rdir}")
    ok = counts["FAIL"] == 0 and (not strict or (counts["SKIP"] + counts["BLOCKED"]) == 0)
    if strict and not ok and counts["FAIL"] == 0:
        print("STRICT: SKIP/BLOCKED 视为未过（T2 落码）")
    return 0 if ok else 1, rdir


def render_report(preset, verdicts, counts):
    L = [f"# {preset.get('title', preset['name'])}", "",
         f"profile=`{preset.get('profile', 'standard')}` · 生成时间见 run.json", "",
         "| 检查 | 类型 | 状态 | 依据 | 耗时 |", "|---|---|---|---|---|"]
    for v in verdicts:
        tag = " **[负控]**" if v.get("negative_control") else ""
        L.append(f"| {v['id']} | {v['type']} | **{v['status']}**{tag} | {v['why']} | {v['ms']} ms |")
    L += ["", f"合计：PASS {counts['PASS']} / FAIL {counts['FAIL']} / SKIP {counts['SKIP']} / BLOCKED {counts['BLOCKED']}", "",
          "负控（`expect_status: FAIL`）的 FAIL 是按设计变红，不是缺陷；它证明这台子有能力变红。", ""]
    if preset.get("notes"):
        L += ["## 边界", "", preset["notes"].strip(), ""]
    return "\n".join(L)


COLORS = {"PASS": "#7ee2a8", "FAIL": "#ff7b72", "SKIP": "#8b949e", "BLOCKED": "#d9a441"}


def render_html(preset, verdicts, counts, meta):
    rows = "".join(
        f"<tr><td class=i>{html.escape(v['id'])}{' <span class=neg>负控</span>' if v.get('negative_control') else ''}</td>"
        f"<td class=t>{v['type']}</td>"
        f"<td class=s style=color:{COLORS[v['status']]}>{v['status']}</td>"
        f"<td class=w>{html.escape(v['why'])}</td><td class=m>{v['ms']}</td></tr>" for v in verdicts)
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(preset.get('title','bench'))}</title>
<style>body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0f1216;color:#e8eaed;margin:0;padding:32px}}
h1{{font-size:19px;margin:0 0 4px}}p.sub{{color:#8b949e;font-size:12.5px;margin:0 0 20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}tr{{border-bottom:1px solid #23272e}}
td{{padding:9px 8px;vertical-align:top}}.i{{font-family:ui-monospace,Consolas,monospace;width:34%}}
.t{{color:#8b949e;width:9%}}.s{{width:9%;font-weight:600}}.w{{color:#c9ccd1}}.m{{color:#6e7681;width:7%;text-align:right}}
.kpi{{display:flex;gap:22px;margin:0 0 20px;font-size:14px}}b{{font-size:20px;font-variant-numeric:tabular-nums}}
.neg{{font-size:10px;color:#d9a441;border:1px solid #6b4a1e;border-radius:9px;padding:1px 6px;margin-left:6px;vertical-align:2px}}</style>
<h1>{html.escape(preset.get('title','bench'))}</h1>
<p class=sub>{html.escape(meta['run_id'])} · {html.escape(meta['os'])} · python {meta['python']}</p>
<div class=kpi><span>PASS <b style=color:#7ee2a8>{counts['PASS']}</b></span><span>FAIL <b style=color:#ff7b72>{counts['FAIL']}</b></span>
<span>SKIP <b style=color:#8b949e>{counts['SKIP']}</b></span><span>BLOCKED <b style=color:#d9a441>{counts['BLOCKED']}</b></span></div>
<table><tr><td class=i>检查</td><td class=t>类型</td><td class=s>状态</td><td class=w>依据</td><td class=m>ms</td></tr>{rows}</table>"""


def main():
    ap = argparse.ArgumentParser(description="复用型验收台")
    ap.add_argument("preset", nargs="?", default="list")
    ap.add_argument("--offline", action="store_true", help="跳过联网检查")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--prune", type=int, default=0, help="只保留最近 N 次运行目录")
    ap.add_argument("--strict", action="store_true", help="SKIP/BLOCKED 也算未过（T2 落码）；门禁场合必须加")
    a = ap.parse_args()
    if a.preset in ("list", "--list"):
        seen = {}
        for d in PRESETS_DIRS:
            for p in sorted(d.glob("*.json")):
                seen.setdefault(p.stem, p)
        for name, p in sorted(seen.items()):
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"{d.get('name', name):<22} {d.get('title', '')}")
        return 0
    if a.prune:
        dirs = sorted([d for d in RUNS.iterdir() if d.is_dir() and not d.is_symlink()],
                      key=lambda d: d.name, reverse=True)
        for d in dirs[a.prune:]:
            shutil.rmtree(d, ignore_errors=True)
            print(f"pruned {d.name}")
    preset = load_preset(a.preset)
    rc, rdir = execute(preset, offline=a.offline, strict=a.strict)
    if a.json:
        print(json.dumps(json.loads((rdir / "verdicts.json").read_text(encoding="utf-8")), ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
