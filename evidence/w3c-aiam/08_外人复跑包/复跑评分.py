#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对两份外人复跑结果。

用法：
    python 复跑评分.py                      # 用随包的示例跑一遍（自检）
    python 复跑评分.py 参考.json 复跑.json   # 实际比对

判定口径：以参考文件为基准，逐行比对。
  MATCH     判定相同
  DIVERGE   判定不同（非危险方向）
  CRITICAL  参考为 NA/NS，而对方判 S —— 缺口被判成"已履行"，最危险的一类
  MISSING   一行缺失
退出码：全部 MATCH 为 0，否则 1。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REF = HERE / "示例_参考.json"
DEFAULT_RUN = HERE / "示例_复跑.json"
REPORT = HERE / "比对报告.md"

DET = {"S", "NS", "NA"}
VERDICTS = {"agree", "disagree", "read_point_insufficient", "insufficient"}
# 关键行：这几行的判定决定整份提案的性质，任何分歧都算不通过。
KEY_ROWS = {"1", "2", "4", "7"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def row_key(row: dict) -> str:
    """R1 / O1 / row-1 统一成 1。"""
    m = re.search(r"(\d+)", str(row.get("row", "")))
    return m.group(1) if m else str(row.get("row", ""))


def pick(row: dict) -> str:
    for key in ("determination", "verdict"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ref_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REF
    run_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RUN
    if not ref_path.exists() or not run_path.exists():
        print(f"找不到文件：{ref_path} 或 {run_path}")
        return 2

    ref, run = load(ref_path), load(run_path)
    ref_rows = {row_key(r): r for r in ref.get("rows", [])}
    run_rows = {row_key(r): r for r in run.get("rows", [])}

    verify_mode = any(pick(r) in VERDICTS for r in ref.get("rows", []))

    lines = []
    lines.append("# 比对报告")
    lines.append("")
    lines.append(f"- 参考：`{ref_path.name}`（{ref.get('runner', {}).get('name', '未署名')}）")
    lines.append(f"- 复跑：`{run_path.name}`（{run.get('runner', {}).get('name', '未署名')}）")
    lines.append(f"- 模式：{'核对模式（agree/disagree）' if verify_mode else '复跑模式（S/NS/NA）'}")
    lines.append("")
    lines.append("| 行 | 义务 | 参考 | 复跑 | 结论 |")
    lines.append("|---|---|---|---|---|")

    counts = {"MATCH": 0, "DIVERGE": 0, "CRITICAL": 0, "MISSING": 0}
    critical_rows = []
    key_divergences = []

    for key in sorted(ref_rows, key=lambda k: (len(k), k)):
        r = ref_rows[key]
        short = r.get("obligation_short", "")
        ref_val = pick(r)
        run_row = run_rows.get(key)
        if run_row is None:
            counts["MISSING"] += 1
            lines.append(f"| {r.get('row')} | {short} | {ref_val} | — | MISSING |")
            continue
        run_val = pick(run_row)

        if verify_mode:
            verdict = run_val.lower() if run_val.lower() in VERDICTS else "insufficient"
            if verdict == "agree":
                counts["MATCH"] += 1
                tag = "MATCH"
            elif verdict == "disagree":
                counts["DIVERGE"] += 1
                tag = "DIVERGE"
            else:
                counts["DIVERGE"] += 1
                tag = verdict.upper()
            lines.append(f"| {r.get('row')} | {short} | {ref_val} | {verdict} | {tag} |")
            continue

        if ref_val == run_val:
            counts["MATCH"] += 1
            tag = "MATCH"
        elif run_val == "S" and ref_val in ("NA", "NS"):
            counts["CRITICAL"] += 1
            tag = "**CRITICAL**"
            critical_rows.append((r.get("row"), ref_val, run_row.get("reason", "")))
        else:
            counts["DIVERGE"] += 1
            tag = "DIVERGE"
        if key in KEY_ROWS and ref_val != run_val:
            key_divergences.append(r.get("row"))
        lines.append(f"| {r.get('row')} | {short} | {ref_val} | {run_val} | {tag} |")

    total = sum(counts.values())
    agree = counts["MATCH"]
    rate = agree / total if total else 0.0

    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append(f"- 一致率：**{agree}/{total} = {rate:.0%}**")
    lines.append(f"- 普通分歧 {counts['DIVERGE']}，重点分歧（缺口被判成满足）{counts['CRITICAL']}，缺失 {counts['MISSING']}")
    if key_divergences:
        lines.append(f"- 关键行分歧：{', '.join(key_divergences)}（关键行 = {', '.join(sorted(KEY_ROWS))}）")
    lines.append("")
    passed = rate >= 5 / 7 and counts["CRITICAL"] == 0 and not key_divergences
    if passed:
        lines.append("**验收通过**：≥5/7 一致，无“缺口被判成满足”，关键行无分歧。可进入下一道门（独立 AI 评审）。")
    else:
        lines.append("**验收未通过**。判定应改的改判定，读取点写不清的重写读取点，然后重跑。"
                     "关键行（期限载体、原值取得、授权归属、删除边界）任何一处分歧都不得放行——"
                     "这四行决定整份提案是“缺口清单”还是“已履行清单”。")
    if critical_rows:
        lines.append("")
        lines.append("### 重点分歧明细")
        lines.append("")
        for row, ref_val, reason in critical_rows:
            lines.append(f"- {row}：参考判 {ref_val}，对方判 S。对方理由：{reason or '（未填）'}")

    report = "\n".join(lines)
    print(report)
    REPORT.write_text(report, encoding="utf-8")
    print(f"\n（已写入 {REPORT.name}）")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
