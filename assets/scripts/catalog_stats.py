"""Per-archive / per-extension / per-magic stats over assets/extracted.
Usage: py -3 -I catalog_stats.py <extracted dir> <out json>"""
import collections, json, math, os, sys

def entropy(b):
    if not b: return 0.0
    c = collections.Counter(b); n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())

def magic(b):
    m = b[:4]
    return m.decode('latin1') if all(32 <= x < 127 for x in m) else m.hex()

ex, js = sys.argv[1:3]
out = {}
for arc in sorted(os.listdir(ex)):
    rows = []
    for d, _, fs in os.walk(os.path.join(ex, arc)):
        for fn in fs:
            p = os.path.join(d, fn)
            with open(p, 'rb') as f: head = f.read(4096)
            rel = os.path.relpath(p, os.path.join(ex, arc)).replace(os.sep, '/')
            ext = os.path.splitext(fn)[1].lower() or '(none)'
            rows.append(dict(path=rel, ext=ext, size=os.path.getsize(p), magic=magic(head),
                             head=head[:16].hex(), ent=round(entropy(head), 2)))
    out[arc] = rows
json.dump(out, open(js, 'w'), indent=0)
for arc, rows in out.items():
    print(f'== {arc}: {len(rows)} files, {sum(r["size"] for r in rows)/2**20:.1f} MiB')
    by = collections.defaultdict(list)
    for r in rows: by[r['ext']].append(r)
    for ext, rs in sorted(by.items(), key=lambda kv: -sum(r['size'] for r in kv[1])):
        mg = collections.Counter(r['magic'] for r in rs).most_common(3)
        dirs = collections.Counter(r['path'].rsplit('/', 1)[0] for r in rs).most_common(2)
        hi = sum(r['ent'] > 7.5 for r in rs)
        print(f'  {ext:8} {len(rs):5} {sum(r["size"] for r in rs)/2**20:8.2f} MiB magic={mg} dirs={dirs} hiEnt={hi}')
