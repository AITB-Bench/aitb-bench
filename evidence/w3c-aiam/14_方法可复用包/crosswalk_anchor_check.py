#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crosswalk_anchor_check — 通用版锚点核对器。

把"某条判定所依赖的原文片段"写进一份 JSON 规格里，逐条回原文查：
  1) must 里的片段必须出现（防编造字段名、编造措辞）
  2) must_not 里的词必须不出现（防"我没找到"被写成"不存在"）
  3) 可限定在某两段标记之间查询（防用别节文字给本节作证）

用法：
    python crosswalk_anchor_check.py spec.json
退出码：全过 0，有失败 1。
零依赖，纯标准库；换协议/换法条时只改 JSON，不改代码。
"""

import io
import json
import os
import re
import sys


def norm(s):
    return re.sub(r'[ \t\r\n\u3000]+', ' ', s)


def slice_section(text, start, end):
    if not start:
        return text
    idx = [m.start() for m in re.finditer(start, text)]
    if not idx:
        return ''
    s = idx[-1]
    if not end:
        return text[s:]
    m = re.search(end, text[s + 10:])
    return text[s:(s + 10 + m.start())] if m else text[s:]


def main():
    if len(sys.argv) < 2:
        print('usage: python crosswalk_anchor_check.py spec.json')
        return 2
    spec_path = sys.argv[1]
    base = os.path.dirname(os.path.abspath(spec_path))
    with io.open(spec_path, 'r', encoding='utf-8') as f:
        spec = json.load(f)

    rows, failed = [], 0
    for chk in spec['checks']:
        src = os.path.normpath(os.path.join(base, chk['source']))
        if not os.path.exists(src):
            failed += 1
            rows.append((chk['id'], chk.get('claim', ''), False, ['源文件缺失：' + chk['source']], []))
            continue
        with io.open(src, 'r', encoding='utf-8', errors='replace') as f:
            text = norm(f.read())
        scope = slice_section(text, chk.get('start'), chk.get('end'))
        missing = [t for t in chk.get('must', []) if t not in scope]
        present = [t for t in chk.get('must_not', []) if t.lower() in scope.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((chk['id'], chk.get('claim', ''), ok, missing, present))

    print('=' * 70)
    print('%s — %s' % (spec.get('title', 'anchor check'), spec_path))
    print('=' * 70)
    for rid, claim, ok, missing, present in rows:
        print('\n[%s] %s' % (rid, 'PASS' if ok else 'FAIL'))
        if claim:
            print('   %s' % claim)
        for t in missing:
            print('   缺原文锚点：%r' % t)
        for t in present:
            print('   反向命中（本应不存在）：%r' % t)
    print('\n' + '-' * 70)
    print('结果：%d/%d 通过' % (len(rows) - failed, len(rows)))
    if failed:
        print('结论：未通过。对应判定不得对外。')
        return 1
    print('结论：锚点均可在原文中复现（不等于判定正确）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
