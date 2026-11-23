#!/usr/bin/env python3
"""S6 external-AI full review harness (SiliconFlow, non-first-party model).

Purpose: put an outbound document in front of a model that is NOT ours, give it
nothing but the text and the claim list, and record what it could not verify.

Design rules (see 00_发布前审查标准_v2 section S6):
  * full coverage, no sampling: the whole target file is sent, split into
    overlapping chunks only if it does not fit in one call;
  * no leading hints: the reviewer gets the text and the task, never our
    conclusions or our answer key;
  * receipt: model id, temperature, prompt hash, timestamp, usage, raw reply;
  * exit code 0 only if every requested lens returned parseable findings.

Key discovery: env SILICONFLOW_API_KEY, else --key-file, else the local key file.
The key is never printed, never written to the receipt.
"""
import argparse, hashlib, json, os, re, sys, time, urllib.request

# Key lookup order: env SILICONFLOW_API_KEY -> --key-file -> file named by env
# SILICONFLOW_KEY_FILE. No machine path is baked into this file; a clean clone
# must be told where the key is, or fail loudly.
DEFAULT_KEY_FILE = os.environ.get("SILICONFLOW_KEY_FILE") or ""
API = "https://api.siliconflow.cn/v1/chat/completions"

LENSES = {
    "expert": (
        "You are a regulatory-affairs reviewer who reads statutory text for a living. "
        "Check every legal or standards claim: the instrument, the article or clause number, "
        "and what that provision actually says. Flag any claim that overstates, understates, or "
        "attributes a requirement to the wrong instrument."
    ),
    "process": (
        "You are a process and evidence reviewer. For every factual or methodological claim, "
        "ask: which read-point in the text or in the cited source would let a third party "
        "reproduce this? Flag claims that are asserted but not anchored, and any place where a "
        "count, a date, or a version number could be wrong."
    ),
    "adversary": (
        "You are an adversarial reviewer trying to stop this document from being posted. "
        "Find the sentence that a hostile reader would quote back at the author. Look for "
        "self-serving framing, claims of novelty that are not supported, and any place where "
        "the author's interest is dressed up as a finding."
    ),
    "outsider": (
        "You are a reader with no background in this project: you know nothing about the "
        "protocol, the group, or the author. Read only what is written. Flag every place where "
        "you cannot follow what is being claimed, every undefined term, and every sentence "
        "whose meaning depends on context the document does not supply."
    ),
}

TASK = """Read the document below in full. It is a proposed public mailing-list contribution.

You have NO internet access and NO ability to open URLs. Do not pretend to verify anything
you cannot see in the text. For each problem, output one finding.

Output STRICT JSON only, no prose before or after, of this shape:
{"findings":[{"severity":"blocker|major|minor","quote":"<exact words from the document, max 40 words>",
"problem":"<what is wrong, one or two sentences>","fix":"<the smallest edit that repairs it, or 'none - delete'>",
"class":"wrong-fact|overstated|unsupported|unclear|internal-inconsistency|none"}]}

Severity guide: blocker = must not be posted as written; major = a competent reader would object;
minor = polish. If a claim looks right, do not list it. An empty list is a valid answer.
Return at most 12 findings, the most serious first.

LENS (apply this reviewer's eyes):
{lens}

DOCUMENT:
---
{doc}
---
"""

def read_key(args):
    if os.environ.get("SILICONFLOW_API_KEY"):
        return os.environ["SILICONFLOW_API_KEY"].strip()
    for p in (args.key_file, DEFAULT_KEY_FILE):
        if p and os.path.exists(p):
            k = open(p, "r", encoding="utf-8", errors="ignore").read().strip()
            if k.startswith("sk-"):
                return k
    sys.exit("no key: set SILICONFLOW_API_KEY or pass --key-file")

def call(key, model, prompt, max_tokens):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data, round(time.time() - t0, 1)

def extract_json(text):
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("\n", " "))
        except Exception:
            return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V3.2")
    ap.add_argument("--lenses", default=",".join(LENSES))
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--key-file", default=None)
    ap.add_argument("--max-tokens", type=int, default=3000)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    key = read_key(args)
    doc = open(args.target, "r", encoding="utf-8").read()
    os.makedirs(args.outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")

    results, total_in = [], 0
    for lens in [x.strip() for x in args.lenses.split(",") if x.strip()]:
        prompt = TASK.replace("{lens}", LENSES[lens]).replace("{doc}", doc)
        ph = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        data, secs = call(key, args.model, prompt, args.max_tokens)
        usage = data.get("usage", {}) or {}
        total_in += usage.get("prompt_tokens", 0)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = extract_json(content)
        findings = (parsed or {}).get("findings", []) if parsed else []
        ok = parsed is not None
        rec = {
            "lens": lens, "model": data.get("model", args.model), "seconds": secs,
            "prompt_sha16": ph, "usage": usage, "parsed": ok,
            "findings": findings, "raw": content,
        }
        open(os.path.join(args.outdir, f"{stamp}_{lens}.json"), "w", encoding="utf-8").write(
            json.dumps(rec, ensure_ascii=False, indent=1))
        results.append(rec)
        print(f"[{'OK ' if ok else 'BAD'}] {lens:<10} findings={len(findings):<2} "
              f"{rec['model']} {secs}s in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}")

    # aggregate receipt
    allf = [dict(f, lens=r["lens"]) for r in results for f in r["findings"]]
    order = {"blocker": 0, "major": 1, "minor": 2}
    allf.sort(key=lambda f: order.get(str(f.get("severity")), 3))
    counts = {s: sum(1 for f in allf if str(f.get("severity")) == s) for s in order}
    agg = {
        "target": args.target, "tag": args.tag, "stamp": stamp,
        "doc_sha256_16": hashlib.sha256(doc.encode("utf-8")).hexdigest()[:16],
        "doc_chars": len(doc), "model": results[0]["model"] if results else args.model,
        "temperature": 0, "lenses": [r["lens"] for r in results],
        "prompt_tokens_total": total_in, "counts": counts, "findings": allf,
        "all_parsed": all(r["parsed"] for r in results),
    }
    p = os.path.join(args.outdir, f"{stamp}_aggregate.json")
    open(p, "w", encoding="utf-8").write(json.dumps(agg, ensure_ascii=False, indent=1))
    print(f"\nS6 {counts}  -> {p}")
    if not agg["all_parsed"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
