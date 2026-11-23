#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""link_direct_check — 引用链接"直达且内容对"检查器（零依赖，裸访问）

判据（S7 的机器部分）：
  1) 不带任何凭据的裸 GET（不用 token / cookie），跟随重定向；
  2) HTTP 200；
  3) 正文里必须出现 spec 中该条的 must 片段之一（大小写不敏感）。
     状态码只是必要条件：旧版与新版都可能 200，只有"内容标记"才是硬证据。

用法：
  python link_direct_check.py links.json
  python link_direct_check.py links.json --only E9,V1
  python link_direct_check.py links.json --json out.json

spec 格式：
{
 "items": [
   {"id":"E1","url":"https://...","must":["片段A","片段B"],"note":"..."},
   {"id":"X","url":"https://...","must":[], "allow_empty": true}   # 刚发出的帖子可能延迟渲染
 ]
}

退出码：0 全过；1 有 FAIL。
"""

import io
import json
import sys
import time
import urllib.request
import urllib.error

UA = 'Mozilla/5.0 (compatible; link-direct-check/1.0)'


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return r.status, r.geturl(), body


def decode(body):
    for enc in ('utf-8', 'latin-1'):
        try:
            return body.decode(enc, errors='replace')
        except Exception:
            continue
    return ''


def norm(s):
    return ' '.join(s.split())


def check(item, timeout=30):
    url = item['url']
    must = [m for m in item.get('must', []) if m]
    try:
        status, final, body = fetch(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        return {'id': item['id'], 'url': url, 'ok': False, 'status': e.code,
                'why': 'HTTP %s' % e.code}
    except Exception as e:
        return {'id': item['id'], 'url': url, 'ok': False, 'status': None,
                'why': '%s: %s' % (type(e).__name__, str(e)[:80])}

    text = norm(decode(body))
    blocked = item.get('blocked_status', [])
    if status in blocked:
        # 官方站点反爬（例如 EUR-Lex 对脚本返回 202 且空体）。人不一定打不开，
        # 所以既不算 PASS（外人无法脚本核对），也不算 FAIL（页面确实存在）。
        return {'id': item['id'], 'url': url, 'ok': True, 'blocked': True,
                'status': status, 'why': 'BLOCKED：官方站点反爬（%s），须人工浏览器复核' % status}
    if status != 200:
        return {'id': item['id'], 'url': url, 'ok': False, 'status': status,
                'why': 'status %s' % status}

    if not must:
        if item.get('allow_empty') and len(text) < 200:
            return {'id': item['id'], 'url': url, 'ok': True, 'status': status,
                    'why': '200 but body short（延迟渲染，按允许处理）', 'len': len(text)}
        return {'id': item['id'], 'url': url, 'ok': True, 'status': status,
                'why': '200', 'len': len(text)}

    low = text.lower()
    hit = [m for m in must if m.lower() in low]
    if not hit:
        return {'id': item['id'], 'url': url, 'ok': False, 'status': status,
                'why': '内容不匹配（无任一 must 片段）', 'len': len(text),
                'missing': must}
    return {'id': item['id'], 'url': url, 'ok': True, 'status': status,
            'why': '200 + 内容命中 %d/%d' % (len(hit), len(must)), 'len': len(text),
            'hit': hit}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    spec_path = argv[1]
    only = None
    out_json = None
    if '--only' in argv:
        only = set(x.strip() for x in argv[argv.index('--only') + 1].split(','))
    if '--json' in argv:
        out_json = argv[argv.index('--json') + 1]

    with io.open(spec_path, 'r', encoding='utf-8') as f:
        spec = json.load(f)

    items = spec['items']
    if only:
        items = [i for i in items if i['id'] in only]

    print('=' * 78)
    print('link_direct_check — 裸访问 · 200 · 内容标记   （%d 条）' % len(items))
    print('=' * 78)

    results = []
    for it in items:
        r = check(it)
        results.append(r)
        flag = 'PASS' if r['ok'] else 'FAIL'
        line = '[%s] %-4s %s' % (flag, r['id'], r['url'])
        print(line)
        print('        %s' % r['why'])
        if not r['ok'] and r.get('missing'):
            for m in r['missing']:
                print('        缺片段: %r' % m)

    ok = sum(1 for r in results if r['ok'] and not r.get('blocked'))
    blk = [r for r in results if r.get('blocked')]
    bad = [r for r in results if not r['ok'] and not r.get('blocked')]
    print('\n' + '-' * 78)
    print('结果：%d/%d 直达且内容匹配；另有 %d 条被官方站点反爬挡在脚本之外' % (ok, len(results), len(blk)))
    if blk:
        print('BLOCKED（须人工浏览器复核，不计为通过）：' + ', '.join(r['id'] for r in blk))
    if bad:
        print('未过：' + ', '.join(r['id'] for r in bad))
    else:
        print('结论：除被反爬挡住的条目外，全部裸访问 200 且内容标记命中（状态码不是证据，标记才是）。')

    if out_json:
        with io.open(out_json, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'checked_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'ok': ok, 'total': len(results), 'items': results},
                               ensure_ascii=False, indent=1))

    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
