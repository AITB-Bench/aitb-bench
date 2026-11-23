#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点自检：把 7 行判定引用的原文锚点，逐条回到 -03 正文里核对是否存在。
用途：防"读取点"是我方编出来的。任何一条 fail，对应行的判定即不得对外。
用法：python 锚点自检.py
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '01_证据链', 'raw2', '13_协议-03_正文.txt')


def load():
    with io.open(SRC, 'r', encoding='utf-8') as f:
        return f.read()


def section(text, start_pat, end_pat):
    """截取从 start_pat 最后一次出现到 end_pat 第一次出现之间的正文。"""
    idx = [m.start() for m in re.finditer(start_pat, text)]
    if not idx:
        return ''
    s = idx[-1]
    m = re.search(end_pat, text[s + 10:])
    e = s + 10 + m.start() if m else len(text)
    return text[s:e]


def norm(s):
    return re.sub(r'[ \t\r\n]+', ' ', s)


def main():
    text = norm(load())
    s21 = section(text, r'2\.1\.\s*Cell shape', r'2\.2\.\s*Identity')
    s25 = section(text, r'2\.5\.\s*Audit log', r'2\.6\.\s*Sharing')
    s27 = section(text, r'2\.7\.\s*Erasure', r'2\.8\.\s*Order of effect')
    s14 = section(text, r'1\.4\.', r'1\.5\.')

    # (编号, 判定所依赖的断言, 应存在的原文片段, 不应存在的词, 限定在该节的原文)
    checks = [
        ('R1', '期限只存在于运营方声明（术语定义在 §1.4，字段在 §2.1 是自由字符串）',
         ['a named, operator-chosen persistence class with stated durability and retention properties',
          'Tier names carry no protocol semantics'],
         [], s14),
        ('R1b', '单元元组里没有期限字段（期限不进记录）',
         ['tier: short ASCII string naming the storage tier'],
         ['retention', 'durability'], s21),
        ('R2', '改后原值可按旧 cellId 取回（仅限不可静默覆盖）',
         ['recompute cellId',
          'MUST refuse to serve a cell whose stored cellId does not match',
          'SHA-256'],
         [], s21),
        ('R3', '单元无 reason / actor / supersession 字段',
         ['cellId, holderId, kekVersion, tier, cellNonce, ciphertext, signature, timestamp'],
         ['reason', 'supersed'], s21),
        ('R4', '持有人身份由 ML-DSA-65 公钥绑定',
         ['holderId: 32-byte holder identifier: the SHA-256 digest of the holder'],
         [], s21),
        ('R5', '删除已执行、可被任何观察者重建（收据 + 公共删除列表）',
         ['write a FORGET receipt for the cellId to the audit log',
          'a public, append-only set of erased cellIds',
          'MUST NOT return an erased cell to anyone'],
         [], s27),
        ('R5b', '所声明的删除类别只能在运营方文档里读到，格式内无字段',
         ['MUST state in its published documentation which class it provides',
          'Clients MUST NOT assert either class'],
         ['erasureClass', 'erasure_class'], s27),
        ('R5c', 'destructionAnchor 出现在工具返回面（§2.5 收据段）',
         ['returns it as destructionAnchor'],
         [], s25),
        ('R6', 'FORGET 收据可按四键检索并验签',
         ['list entries by subjectId, by holderId and by operation',
          'every FORGET receipt',
          'check the receipt\'s signature against the holder\'s public key'],
         [], s25),
        ('R7', '收据体系无边界字段（该删/该留）',
         ['receiptId, subjectId, operation, holderId, signature, timestamp, receiptNonce'],
         ['obligation', 'lawful basis', 'retention basis'], s25 + ' ' + s27),
    ]

    rows = []
    failed = 0
    for rid, claim, must, must_not, scope in checks:
        missing = [t for t in must if t not in scope]
        present = [t for t in must_not if t.lower() in scope.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((rid, claim, ok, missing, present))

    # ---- 第二组：法规原文锚点（防引用法条时编造措辞） ----
    statutes = [
        ('S1', 'HIPAA 6 年、起算取"创建日或最后生效日"之较晚者', 'raw2/15_HIPAA_164.316.txt',
         ['for 6 years from the date of its creation or the date when it last was in effect, whichever is later'], []),
        ('S2', 'PIPEDA 只留必要，且要求同时给出最短与最长', 'raw2/10_PIPEDA_FullText.html',
         ['retained only as long as necessary for the fulfilment of those purposes',
          'minimum and maximum retention periods'], []),
        ('S3', 'PIPL 最短必要上限 + 停止除存储外处理 + 三年', 'raw2/14_PIPL_全文.txt',
         ['实现处理目的所必要的最短时间',
          '停止除存储和采取必要的安全保护措施之外的处理',
          '至少保存三年'], []),
        ('S4', 'LGPD 第 16 条删除与例外、第 37 条处理记录', 'raw2/09_LGPD_Lei13709.html',
         ['Art. 16', 'Art. 37'], []),
        ('S5', 'GDPR 删除须"无不当迟延"', 'raw2/16_GDPR_art-17-gdpr.txt',
         ['the erasure of personal data concerning him or her without undue delay'], []),
        ('S6', 'GDPR 可携带须为结构化、通用、机器可读格式并可传输', 'raw2/16_GDPR_art-20-gdpr.txt',
         ['structured, commonly used and machine-readable format',
          'transmit those data to another controller'], []),
        ('S7', 'PIPL 可携带须提供转移途径', 'raw2/14_PIPL_全文.txt',
         ['转移至其指定的个人信息处理者'], []),
    ]
    for rid, claim, rel, must, must_not in statutes:
        path = os.path.normpath(os.path.join(HERE, '..', '01_证据链', rel))
        if not os.path.exists(path):
            failed += 1
            rows.append((rid, claim, False, ['文件缺失：' + rel], []))
            continue
        with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
            body = norm(f.read())
        missing = [t for t in must if t not in body]
        present = [t for t in must_not if t.lower() in body.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((rid, claim, ok, missing, present))

    # ---- 第三组：已通过的 charter v1.1（防把"被采纳"写得比事实更硬） ----
    # V4 是反向检查：v1.1 正文里没有"医疗器械"字样。我方 10-21 提出的
    # "所列器械法域是举例而非穷举"这一点，落在主席 11-03 的书面读法里，
    # 没有写进 charter 正文。对外只能说"读法纳入"，不能说"写入正文"。
    charter = [
        ('V1', '我方提出的一句话已原样进入 v1.1 正文（§2）', 'raw2/18_charter_v1.1_20261123.txt',
         ['re-examines that deliverable as a decision under §9',
          'rather than leaving it pinned to a text that no longer says what it said'], []),
        ('V2', 'v1.1 自述 §3 范围未改（改的是读法与 §13）', 'raw2/18_charter_v1.1_20261123.txt',
         ['Scope (§3) is unchanged'], []),
        ('V3', 'v1.1 §3 仍点名可比法域清单', 'raw2/18_charter_v1.1_20261123.txt',
         ['comparable regimes (HIPAA, PIPEDA, PIPL, LGPD)'], []),
        ('V4', 'v1.1 正文不含"medical device"措辞（器械法域只在书面读法里纳入）', 'raw2/18_charter_v1.1_20261123.txt',
         [], ['medical device', 'medical-device']),
    ]
    for rid, claim, rel, must, must_not in charter:
        path = os.path.normpath(os.path.join(HERE, '..', '01_证据链', rel))
        if not os.path.exists(path):
            failed += 1
            rows.append((rid, claim, False, ['文件缺失：' + rel], []))
            continue
        with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
            body = norm(f.read())
        missing = [t for t in must if t not in body]
        present = [t for t in must_not if t.lower() in body.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((rid, claim, ok, missing, present))

    # ---- 第四组：W3C Team 正式通知（第三方来源，只确认状态，不评价内容） ----
    notice = [
        ('V5', 'W3C Team 通知确认 v1.1 于 2026-11-23 通过', 'raw3/0009.html',
         ['Status: v1.1 — Adopted on 2026-11-23'], []),
    ]
    for rid, claim, rel, must, must_not in notice:
        path = os.path.normpath(os.path.join(HERE, '..', '01_证据链', rel))
        if not os.path.exists(path):
            failed += 1
            rows.append((rid, claim, False, ['文件缺失：' + rel], []))
            continue
        with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
            body = norm(f.read())
        missing = [t for t in must if t not in body]
        present = [t for t in must_not if t.lower() in body.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
            rows.append((rid, claim, ok, missing, present))
        else:
            rows.append((rid, claim, ok, missing, present))

    # ---- 第五组：charter 对我方定位的两处措辞（防"第四项交付物/属 informative"写错） ----
    positioning = [
        ('V6', '§3 把 crosswalk 写为 informative 的第 4 项 in-scope 工作', 'raw2/18_charter_v1.1_20261123.txt',
         ['A regulatory crosswalk pack (informative): mappings from the referenced protocol'], []),
        ('V7', '§5 交付物清单里 crosswalk 为 informative，映射即 §3 所列', 'raw2/18_charter_v1.1_20261123.txt',
         ['Regulatory crosswalk pack (informative) — the mappings enumerated in §3'], []),
    ]
    for rid, claim, rel, must, must_not in positioning:
        path = os.path.normpath(os.path.join(HERE, '..', '01_证据链', rel))
        if not os.path.exists(path):
            failed += 1
            rows.append((rid, claim, False, ['文件缺失：' + rel], []))
            continue
        with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
            body = norm(f.read())
        missing = [t for t in must if t not in body]
        present = [t for t in must_not if t.lower() in body.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((rid, claim, ok, missing, present))

    # ---- 第六组：协议自己承认的"没承载"（R13 的最强依据） ----
    x = [
        ('X1', '-03 §9.1 承认运营方仍负"无不当迟延"删除责任，即协议知道该义务而不承载', 'raw2/13_协议-03_正文.txt',
         ['remain responsible for erasure without undue delay'], []),
    ]
    for rid, claim, rel, must, must_not in x:
        path = os.path.normpath(os.path.join(HERE, '..', '01_证据链', rel))
        body = norm(io.open(path, 'r', encoding='utf-8', errors='replace').read())
        missing = [t for t in must if t not in body]
        present = [t for t in must_not if t.lower() in body.lower()]
        ok = not missing and not present
        if not ok:
            failed += 1
        rows.append((rid, claim, ok, missing, present))

    print('=' * 78)
    print('锚点自检 — 判定所依赖的原文锚点 vs draft-saihm-memory-protocol-03 正文')
    for rid, claim, ok, missing, present in rows:
        print('\n[%s] %s' % (rid, 'PASS' if ok else 'FAIL'))
        print('   断言：%s' % claim)
        if missing:
            print('   缺原文锚点：')
            for t in missing:
                print('     - %r' % t)
        if present:
            print('   反向检查命中（本应不存在的词）：')
            for t in present:
                print('     - %r' % t)
    print('\n' + '-' * 78)
    print('结果：%d/%d 通过' % (len(rows) - failed, len(rows)))
    if failed:
        print('结论：未通过。对应行的判定在外部实测前不得对外。')
        return 1
    print('结论：全部锚点可在原文中复现，判定具备可核基础（不等于判定正确）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
