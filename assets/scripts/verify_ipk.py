"""Independently parse IPK1 tables (recursively) and check blipks output.

Usage: py -3 -I verify_ipk.py <game_files dir> <extracted dir> <out json>
Mirrors blipks-unpack path rules: '\'->'/', top-level entries of media.ipk get a
'media/' prefix, nested .ipk files are recursed (not written), first writer of
a path wins (Windows: case-insensitive).
"""
import hashlib, json, os, struct, sys

def walk(f, base, name, depth, out, nested):
    f.seek(base)
    magic, align, n, size = struct.unpack('<4sIII', f.read(16))
    assert magic == b'IPK1', (name, magic)
    nested.append(dict(name=name, depth=depth, align=align, entries=n, size=size, base=base))
    recs = [struct.unpack('<64sIIII', f.read(80)) for _ in range(n)]
    for raw, comp, sz_ipk, off, sz_disk in recs:
        p = raw.split(b'\0', 1)[0].decode('ascii').replace(chr(92), '/')
        if p.lower().endswith('.ipk'):
            walk(f, base + off, p.rsplit('/', 1)[-1], depth + 1, out, nested)
            continue
        f.seek(base + off)
        h = hashlib.sha1(f.read(sz_ipk)).hexdigest()
        outp = ('media/' + p) if name == 'media.ipk' else p
        out.append(dict(ipk=name, path=p, out=outp, comp=comp, sz_ipk=sz_ipk, sz_disk=sz_disk, sha1=h))

def main(gf, ex, js):
    report = {}
    for fn in sorted(os.listdir(gf)):
        if not fn.lower().endswith('.ipk'):
            continue
        ents, nested = [], []
        with open(os.path.join(gf, fn), 'rb') as f:
            walk(f, 0, fn, 0, ents, nested)
        root = os.path.join(ex, fn[:-4])
        first, conflicts, missing, badsize = {}, [], [], []
        for e in ents:
            k = e['out'].lower()
            if k in first:
                a = first[k]
                if a['sha1'] != e['sha1'] and not (a['sz_disk'] == e['sz_disk'] and a['comp'] != e['comp']):
                    conflicts.append([a['ipk'], a['out'], e['ipk'], e['out'], a['sz_disk'], e['sz_disk']])
                elif a['sha1'] != e['sha1']:
                    conflicts.append([a['ipk'], a['out'], e['ipk'], e['out'], 'same size, comp differs'])
                continue
            first[k] = e
            fp = os.path.join(root, e['out'])
            if not os.path.isfile(fp):
                missing.append(e['out'])
            elif os.path.getsize(fp) != e['sz_disk']:
                badsize.append([e['out'], e['sz_disk'], os.path.getsize(fp)])
        report[fn] = dict(nested=nested, n_entries=len(ents), n_unique=len(first),
                          n_compressed=sum(e['comp'] for e in first.values()),
                          missing=missing, badsize=badsize, conflicts=conflicts,
                          entries=list(first.values()))
        print(f"{fn}: {len(nested)-1} nested ipk, {len(ents)} entries, {len(first)} unique outputs, "
              f"missing={len(missing)} badsize={len(badsize)} conflicts={len(conflicts)}")
    with open(js, 'w') as o:
        json.dump(report, o, indent=1)

if __name__ == '__main__':
    main(*sys.argv[1:4])
