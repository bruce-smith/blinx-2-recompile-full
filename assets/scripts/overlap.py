"""Cross-archive overlap + MIXF sanity. Usage: py -3 -I overlap.py <extracted dir>"""
import collections, hashlib, os, struct, sys
ex = sys.argv[1]
idx = {}
for arc in sorted(os.listdir(ex)):
    m = {}
    for d, _, fs in os.walk(os.path.join(ex, arc)):
        for fn in fs:
            p = os.path.join(d, fn)
            rel = os.path.relpath(p, os.path.join(ex, arc)).replace(os.sep, '/').lower()
            m[rel] = hashlib.sha1(open(p, 'rb').read()).hexdigest()
    idx[arc] = m
med = idx['media']
for arc in sorted(idx):
    m = idx[arc]
    tops = collections.Counter(k.split('/')[0] for k in m)
    both = [k for k in m if k in med] if arc != 'media' else []
    same = sum(m[k] == med[k] for k in both)
    print(f'{arc}: top dirs {dict(tops)}; shared paths with media.ipk {len(both)} (identical {same})')
us = idx['lng_us']
for arc in [a for a in idx if a.startswith('lng_') and a != 'lng_us']:
    m = idx[arc]
    sub = lambda k: k.replace(arc[4:], 'us')
    common = [k for k in m if not k.startswith(arc + '/')]
    same = sum(us.get(k) == m[k] for k in common)
    loc = [k for k in m if k.startswith(arc + '/')]
    match = sum(sub(k) in us for k in loc)
    print(f'{arc} vs lng_us: non-localized {len(common)} (identical {same}); localized {len(loc)} (name-matched to _us {match})')
# MIXF
bad, n, kinds = [], 0, collections.Counter()
for arc in ('lng_us', 'media'):
    for d, _, fs in os.walk(os.path.join(ex, arc)):
        for fn in fs:
            if not fn.lower().endswith('.mix'): continue
            b = open(os.path.join(d, fn), 'rb').read()
            n += 1
            hsz, names_end, align, _, _, _, cnt = struct.unpack_from('<7I', b, 4)
            body = b[align:align + 4]
            kinds[body] += 1
            if b[:4] != b'MIXF' or body != b'XPR0': bad.append(fn)
print(f'MIXF files checked: {n}; payload magics {dict(kinds)}; non-XPR0: {bad[:10]}')
