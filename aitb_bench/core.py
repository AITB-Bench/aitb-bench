# -*- coding: utf-8 -*-
"""bench.py — 复用型验收台：清单驱动、适配器执行、每次运行产出证据包。

形态取自业界 conformance harness 的通行做法：
  清单(preset) → 逐项检查(adapter) → 每次运行一个证据目录(run.json / verdicts.json / manifest.json)
  → 人读报告(report.md) + 可视化(snapshot.html) → 退出码非零即失败。
零依赖、纯标准库、不联网除显式 http 检查。
"""
import argparse, getpass, hashlib, hmac, html, json, os, platform, shutil, subprocess, sys, time
from pathlib import Path

# Windows 控制台默认 cp936/cp1252，打印中文会 UnicodeEncodeError（GitHub Actions windows runner 实测触发）。
# 统一按 utf-8 输出，编不出来的字符降级为占位，不让编码问题冒充"检查失败"。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BENCH = Path(__file__).resolve().parent

# vars 的取法要同时满足两种运行形态：dev 目录里 `python bench.py`（同目录 import），
# 安装包里 `aitb` 控制台脚本（core.py 属 aitb_bench 包，必须用相对 import）。
# 早期只写 `import vars`，CI 上 aitb demo 直接 ModuleNotFoundError，门禁形同虚设。
try:  # 包内运行
    from . import vars as _VARS
except ImportError:  # 脚本运行
    sys.path.insert(0, str(BENCH))
    import vars as _VARS


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
    """$AITB_RUNS > git 检出根部的 runs（开发/克隆态）> 当前工作目录 runs（安装态，避免写进 site-packages）。"""
    env = os.environ.get("AITB_RUNS")
    if env:
        return Path(env)
    gitroot = next((p for p in [BENCH, *BENCH.parents] if (p / ".git").exists()), None)
    base = (gitroot / "runs") if gitroot else (Path.cwd() / "runs")
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        return Path.cwd() / "runs"


PRESETS_DIRS = _presets_dirs()
PRESETS = PRESETS_DIRS[0] if PRESETS_DIRS else Path.cwd() / "presets"
RUNS = _runs_dir()
VERDICTS = ("PASS", "FAIL", "SKIP", "BLOCKED")


def _version():
    """版本号必须能被证据引用。装成包时取 metadata，源码态退到 0.1.0。

    旧版没有 --version，导致 run.json 里无法绑定工具版本（FC-009）。
    """
    try:
        from importlib.metadata import version as _v
        return _v("aitb-bench")
    except Exception:
        return "0.1.0"


AITB_VERSION = _version()


def sha256_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _kill_tree(pid):
    """超时必须杀整棵进程树（FC-010：旧版只杀 shell，孙进程在封存后仍写文件）。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def run_cmd(cmd, cwd=None, timeout=300, env=None):
    t0 = time.time()
    kw = dict(cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
              text=True, encoding="utf-8", errors="replace", env=env)
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    try:
        p = subprocess.Popen(cmd, shell=isinstance(cmd, str), **kw)
    except Exception as e:
        return 125, f"[exception] {e}", int((time.time() - t0) * 1000)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", int((time.time() - t0) * 1000)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        try:
            out, _ = p.communicate(timeout=15)
        except Exception:
            out = ""
        return 124, (out or "") + f"\n[timeout after {timeout}s; process tree killed]", int((time.time() - t0) * 1000)


# ---------------- adapters ----------------

def a_cmd(spec, ctx):
    """跑一条命令，按 expect 子串判定。cmd/cwd 支持 ${VAR}（配置或环境变量）。

    P0 修正（FC-001/002/003）：非零退出不得因"期望串出现"而判 PASS；
    空判据（expect=""）恒真，必须在判定前拒绝。要放行非零退出，须显式写
    `"allow_nonzero": true`（例如负控或已知返回码的探测脚本）。
    """
    _v = _VARS
    raw_cwd = _v.expand(spec["cwd"]) if spec.get("cwd") else ""
    if raw_cwd:
        cwd = Path(raw_cwd)
        cwd = cwd if cwd.is_absolute() else (Path.cwd() / cwd).resolve()
    else:
        cwd = BENCH
    expect = spec.get("expect")
    if expect is not None and not str(expect).strip():
        return "BLOCKED", "empty-expect：空判据恒真，已被拒绝（需给出非空 expect 或去掉该字段）", "", 0
    cmd = _v.expand(spec["cmd"])
    rc, out, ms = run_cmd(cmd, cwd=cwd, timeout=spec.get("timeout", 300))
    tail = "\n".join([l for l in out.strip().splitlines() if l.strip()][-3:])
    if rc == 124:
        return "BLOCKED", f"超时 {spec.get('timeout', 300)}s（进程树已终止）", tail, ms
    if rc == 125:
        return "BLOCKED", f"命令未能执行（{out.strip()[:80]}）", tail, ms
    allow_nonzero = bool(spec.get("allow_nonzero", False))
    if rc != 0 and not allow_nonzero:
        return "FAIL", f"rc={rc}：非零退出不得判 PASS（即便期望串出现）", tail, ms
    if expect and expect not in out:
        return "FAIL", f"未出现期望串：{expect!r}（rc={rc}）", tail, ms
    return "PASS", (f"含期望串 {expect!r}（rc={rc}）" if expect else f"rc={rc}"), tail, ms


def a_files(spec, ctx):
    """核对文件在场与大小下限。base 可为绝对路径，path 相对 base。"""
    miss = []
    _v = _VARS
    raw = _v.expand(spec["base"]) if spec.get("base") else ""
    if raw:
        base = Path(raw)
        base = base if base.is_absolute() else (Path.cwd() / base).resolve()
    else:
        base = BENCH
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
    blocked = False
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
            blocked = True
            continue
        mark = "ok" if code == want else f"want {want}"
        if code != want:
            ok = False
        out.append(f"{url} -> {code} ({mark})")
    if not ok:
        return "FAIL", "; ".join(out), "", int((time.time() - ms0) * 1000)
    if blocked:
        # 超时/连接不了 ≠ 判据不符：没测到不能算测得失败（T1）
        return "BLOCKED", "; ".join(out), "", int((time.time() - ms0) * 1000)
    return "PASS", "; ".join(out), "", int((time.time() - ms0) * 1000)


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
    """返回提供 expand() 的模块；取不到就返回 None，调用方降级为"不展开变量"。"""
    return _VARS


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


def canonical(obj):
    """规范化 JSON 字节：排序键、紧凑分隔符、UTF-8。所有哈希都基于它。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_obj(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def root_of(files):
    """目录根指纹：对 (name, sha256) 排序后求哈希。少一个文件、多一个文件都会变。"""
    return sha256_obj([[k, files[k]] for k in sorted(files)])


def _executor():
    """执行者身份：节点 + 用户 + （可选）HMAC 证明。

    PoC 用 HMAC-SHA256（共享密钥，来自 AITB_SIGNING_KEY），**不是签名**：
    它只能证明"知道密钥的人跑过"，不能证明"某组织跑过"。正式版换 Sigstore/ed25519。
    """
    ident = {"node": platform.node(), "user": getpass.getuser(), "python": sys.version.split()[0]}
    key = os.environ.get("AITB_SIGNING_KEY")
    if key:
        ident["hmac"] = hmac.new(key.encode("utf-8"), canonical(ident), hashlib.sha256).hexdigest()
        ident["alg"] = "hmac-sha256-poc"
    else:
        ident["alg"] = "none"
    return ident


def execute(preset, offline=False, strict=False):
    run_id = time.strftime("%Y%m%dT%H%M%S")
    rdir = RUNS / f"{run_id}_{preset['name']}"
    rdir.mkdir(parents=True, exist_ok=True)
    prog = rdir / "progress.log"

    def _p(line):
        """每行同时进 progress.log 和 stdout，且立刻 flush。

        Why: 调用方常把 stdout 接管道（tail/grep），管道会缓冲到进程结束，
        于是一次 90 秒的网检看起来像"假死"。progress.log 让任何旁观者都能 tail。
        """
        with open(prog, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    checks = preset.get("checks") or []
    _p(f"[START  ] {preset['name']} {run_id} checks={len(checks)} "
       f"max_s={preset.get('max_seconds', 900)}")
    ctx = {"offline": offline}
    verdicts = []
    if not checks:
        # P0 修正（FC-013 fail-open）：0 条检查的空集合恒真，旧版会 rc=0。
        verdicts.append({"id": "preset.vacuous", "type": "preset", "status": "BLOCKED",
                         "why": "preset 内 0 条检查：空集合恒真，不得判绿",
                         "evidence": "", "ms": 0,
                         "negative_control": False, "negctl_violation": False})
        _p("[BLOCKED]            preset.vacuous                          0 条检查 → 不是通过")
    deadline = time.time() + float(preset.get("max_seconds", 900))
    for spec in checks:
        if time.time() > deadline:
            verdicts.append({"id": spec["id"], "type": spec["type"], "status": "BLOCKED",
                             "why": "全局超时，本项未执行", "evidence": "", "ms": 0})
            _p(f"[BLOCKED]            {spec['id']:<38} 全局超时，本项未执行（不是通过）")
            continue
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
        negctl_violation = False
        if neg and status != "FAIL":
            # P1 修正（FC-004）：旧版把 BLOCKED/SKIP 改写成 FAIL，证据性质被篡改。
            # 现在保留观测到的状态，只标记"负控未变红"，并让它影响退出码（不改写、不吞掉）。
            why = f"负控未变红：要求 FAIL，实得 {status}（{why}）"
            negctl_violation = True
        # want == PASS 时，SKIP / BLOCKED 保持原状：没测到不是测得失败，但会阻止判绿（见 ok 计算）
        verdicts.append({"id": spec["id"], "type": spec["type"], "status": status,
                         "why": why, "evidence": evidence, "ms": ms or int((time.time() - t0) * 1000),
                         "negative_control": neg, "negctl_violation": negctl_violation})
        _p(f"[{status:<7}]{'[NEG-CTRL]' if neg else '          '} {spec['id']:<38} {why}")

    counts = {k: sum(1 for v in verdicts if v["status"] == k) for k in VERDICTS}
    neg_violations = sum(1 for v in verdicts if v.get("negctl_violation"))
    _p(f"[DONE   ] {json.dumps(counts, ensure_ascii=False)} negctl_violations={neg_violations}")
    preset_sha = sha256_obj({k: preset.get(k) for k in sorted(preset)})
    run_meta = {
        "run_id": run_id, "preset": preset["name"], "title": preset.get("title", preset["name"]),
        "started_at": run_id, "host": platform.node(), "os": platform.platform(),
        "python": sys.version.split()[0], "counts": counts, "strict": strict, "offline": offline,
        # P1 修正（FC-006/017）：工具版本与 preset 内容哈希必须进证据，否则"哪版跑的、跑的什么"不可核对
        "aitb_version": AITB_VERSION, "preset_sha256": preset_sha,
        "checks": len(checks), "negctl_violations": neg_violations,
        "executor": _executor(),
    }
    (rdir / "run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "verdicts.json").write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")

    report = render_report(preset, verdicts, counts, run_meta)
    (rdir / "report.md").write_text(report, encoding="utf-8")
    (rdir / "snapshot.html").write_text(render_html(preset, verdicts, counts, run_meta), encoding="utf-8")

    files = {}
    for f in sorted(rdir.iterdir()):
        if f.name != "manifest.json":
            files[f.name] = sha256_file(f)
    manifest = {"run_id": run_id, "aitb_version": AITB_VERSION, "preset": preset["name"],
                "preset_sha256": preset_sha, "counts": counts,
                "negctl_violations": neg_violations, "files": files, "root": root_of(files)}
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
    # P0 修正（FC-015）：BLOCKED 是"没判定"，不是"通过"。旧版只看 FAIL==0，N05/N10 因此 rc=0。
    ok = (counts["FAIL"] == 0 and counts["BLOCKED"] == 0
          and neg_violations == 0 and (not strict or counts["SKIP"] == 0))
    if not ok and counts["FAIL"] == 0:
        print(f"NOT-GREEN: blocked={counts['BLOCKED']} negctl_violations={neg_violations} "
              f"skip={counts['SKIP']} → 未判定/负控失效不得当通过")
    return 0 if ok else 1, rdir


def render_report(preset, verdicts, counts, meta=None):
    meta = meta or {}
    L = [f"# {preset.get('title', preset['name'])}", "",
         f"profile=`{preset.get('profile', 'standard')}` · aitb `{meta.get('aitb_version', '?')}` · "
         f"preset_sha256 `{str(meta.get('preset_sha256', '?'))[:16]}…`", "",
         "| 检查 | 类型 | 状态 | 依据 | 耗时 |", "|---|---|---|---|---|"]
    for v in verdicts:
        tag = " **[负控]**" if v.get("negative_control") else ""
        if v.get("negctl_violation"):
            tag += " **[负控失效]**"
        L.append(f"| {v['id']} | {v['type']} | **{v['status']}**{tag} | {v['why']} | {v['ms']} ms |")
    L += ["", f"合计：PASS {counts['PASS']} / FAIL {counts['FAIL']} / SKIP {counts['SKIP']} / BLOCKED {counts['BLOCKED']}"
          f" · 负控失效 {meta.get('negctl_violations', 0)}", "",
          "负控（`expect_status: FAIL`）的 FAIL 是按设计变红，不是缺陷；它证明这台子有能力变红。", "",
          "**BLOCKED 不是通过**：没判定出来的项一律阻止判绿（`--strict` 再加 SKIP）。", ""]
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
    ap.add_argument("--version", action="version", version=f"aitb {AITB_VERSION}",
                    help="打印工具版本（证据必须能绑定它）")
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
