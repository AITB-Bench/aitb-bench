#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3c-aiam 线一致性探针：把"文档之间互相矛盾"变成可执行判定。
只做机械对账，不做质量评价。通过打印 CONSISTENCY: PASS，否则列出全部不符项。
"""

import io
import os
import re
import sys

# 包根：环境变量 W3C_PKG > config.local.json/config.example.json 的 W3C_PKG > 仓内 evidence/w3c-aiam
_BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BENCH)
try:
    from vars import load_vars
    _V = load_vars()
except Exception:
    _V = {}
def _default_pkg():
    raw = os.environ.get('W3C_PKG') or _V.get('W3C_PKG')
    cands = []
    if raw:
        cands += [raw, os.path.join(_BENCH, raw),
                  os.path.join(os.path.dirname(_BENCH), raw)]
    cands += [os.path.join(_BENCH, 'evidence', 'w3c-aiam'),
              os.path.join(os.path.dirname(_BENCH), 'evidence', 'w3c-aiam')]
    for c in cands:
        if os.path.isdir(c):
            return c
    return os.path.join(_BENCH, 'evidence', 'w3c-aiam')


PKG = _default_pkg()


def read(name):
    p = os.path.join(PKG, name)
    if not os.path.exists(p):
        return None
    with io.open(p, 'r', encoding='utf-8') as f:
        return f.read()


def main():
    bad = []

    # 1. 两份提案的行数与判定计数必须一致
    for name, label in [('04_交叉映射贡献提案.md', '04'), ('04b_提案_list版.md', '04b')]:
        t = read(name)
        if t is None:
            bad.append('%s 缺失' % label)
            continue
        rows = len(re.findall(r'(?m)^\| R\d', t))
        s = len(re.findall(r'\| \*\*S\*\*', t))
        ns = len(re.findall(r'\| \*\*NS\*\*', t))
        na = len(re.findall(r'\| \*\*NA\*\*', t))
        if (rows, s, ns, na) != (15, 4, 7, 4):
            bad.append('%s 行数/判定 = %s/%s/%s/%s，应为 15/4/7/4' % (label, rows, s, ns, na))

    # 2. 04b 必含三段关键声明
    t = read('04b_提案_list版.md') or ''
    for frag in ['Scope, stated plainly', 'fifteen rows',
                 'The protocol does not by itself make an operator compliant']:
        if frag not in t:
            bad.append('04b 缺关键段：%r' % frag)

    # 3. 矩阵副标题必须写 13 行，且写明器械行经读法纳入
    svg = read('07_覆盖矩阵.svg') or ''
    for frag in ['13 行 × 6 轴', 'comparable regimes']:
        if frag not in svg:
            bad.append('07_覆盖矩阵.svg 缺：%r' % frag)

    # 4. 结构性发现必须在位
    t9 = read('09_全法域覆盖说明.md') or ''
    for frag in ['F1', 'F2', 'F3', 'PIPEDA']:
        if frag not in t9:
            bad.append('09 缺：%r' % frag)
    t10 = read('10_第3节点名清单对账与法域补全.md') or ''
    for frag in ['F4', 'N1', 'N2', 'N3', 'LGPD']:
        if frag not in t10:
            bad.append('10 缺：%r' % frag)

    # 5. 证据副本数量
    raw = os.path.join(PKG, '01_证据链', 'raw')
    raw2 = os.path.join(PKG, '01_证据链', 'raw2')
    n1 = len([x for x in os.listdir(raw) if x.endswith('.html')]) if os.path.isdir(raw) else 0
    n2 = len([x for x in os.listdir(raw2)]) if os.path.isdir(raw2) else 0
    if n1 != 8:
        bad.append('raw 归档数 = %d，应为 8' % n1)
    if n2 < 5:
        bad.append('raw2 文件数 = %d，应 ≥ 5' % n2)

    # 6. 评分器自检必须仍然是"验收未通过"（防橡皮章）
    rep = read(os.path.join('08_外人复跑包', '比对报告.md')) or ''
    if '验收未通过' not in rep:
        bad.append('复跑评分自检未显示"验收未通过"，评分器可能已变成橡皮章')

    # 7. 锚点自检结论必须在位
    chk = read(os.path.join('08_外人复跑包', '锚点自检_输出.txt')) or ''
    if '25/25 通过' not in chk:
        bad.append('锚点自检输出不含 25/25 通过')

    # 8. 证据副本完整性：清单记录的 SHA-256 前 16 位必须与实际文件一致
    import hashlib
    lst = read(os.path.join('01_证据链', '证据清单.md')) or ''
    recorded = dict(re.findall(r'\| E([1-8]) \|.*?\| ([0-9A-F]{16}) \|', lst))
    rawdir = os.path.join(PKG, '01_证据链', 'raw')
    files = sorted([x for x in os.listdir(rawdir) if x.endswith('.html')]) if os.path.isdir(rawdir) else []
    if len(recorded) != 8 or len(files) != 8:
        bad.append('证据清单记录 %d 条 / raw 文件 %d 个，应各为 8' % (len(recorded), len(files)))
    for i, fn in enumerate(files, start=1):
        with open(os.path.join(rawdir, fn), 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()[:16]
        want = recorded.get(str(i))
        if want and h != want:
            bad.append('E%d 哈希不符：记录 %s，实际 %s（%s）' % (i, want, h, fn))
        elif not want:
            bad.append('E%d 无记录哈希（%s）' % (i, fn))


    # 9. E9/E10（ charter v1.1 发布页与组主页）作为新增一手证据，哈希同样要与实际一致
    extra = [('9', '18_charter_v1.1_20261123.html'), ('10', '17_group_page_20261123.html')]
    rec2 = dict(re.findall(r'\| E(9|10) \|.*?\| ([0-9A-F]{16}) \|', lst))
    if len(rec2) != 2:
        bad.append('证据清单缺 E9/E10 记录（实得 %d 条）' % len(rec2))
    for key, fn in extra:
        p2 = os.path.join(raw2, fn)
        if not os.path.exists(p2):
            bad.append('E%s 副本缺失：%s' % (key, fn))
            continue
        with open(p2, 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()[:16]
        want = rec2.get(key)
        if not want:
            bad.append('E%s 无记录哈希' % key)
        elif h != want:
            bad.append('E%s 哈希不符：记录 %s，实际 %s' % (key, want, h))

    # 10. E11（W3C Team 正式通知，第三方来源）必须入清单且哈希一致
    rec3 = re.findall(r'\| E11 \|.*?\| ([0-9A-F]{16}) \|', lst)
    p3 = os.path.join(PKG, '01_证据链', 'raw3', '0009.html')
    if not rec3:
        bad.append('证据清单缺 E11（W3C Team 正式通知）')
    elif not os.path.exists(p3):
        bad.append('E11 副本缺失：raw3/0009.html')
    else:
        with open(p3, 'rb') as f:
            h = hashlib.sha256(f.read()).hexdigest().upper()[:16]
        w = rec3[0]
        if w != h:
            bad.append('E11 哈希不符：记录 %s，实际 %s' % (w, h))

    if bad:
        print('CONSISTENCY: FAIL')
        for b in bad:
            print('  - ' + b)
        return 1
    print('CONSISTENCY: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
