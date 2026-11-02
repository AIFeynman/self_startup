import json, collections, sys
def load(p): return {x['name']: x for r in json.load(open(p)) for x in r.get('labels', [])}
tax=json.load(open('/Users/libiao/project/test_feynman/self_startup/docs/designs/oss-radar-taxonomy.json'))
codes={c['code'] for d in tax['domains'] for c in d['children']}
parent={c['code']:d['code'] for d in tax['domains'] for c in d['children']}
a,b=load(sys.argv[1]),load(sys.argv[2])
common=a.keys()&b.keys(); print('common',len(common))
for f in ['k','d','ai']: print(f, round(sum(a[n][f]==b[n][f] for n in common)/len(common),3))
print('d 一级相同', round(sum(parent.get(a[n]['d'])==parent.get(b[n]['d']) for n in common)/len(common),3))
print('d 落在对方 d/d2', round(sum(a[n]['d'] in [b[n]['d']]+(b[n].get('d2') or []) for n in common)/len(common),3))
print('非法 code',[x['d'] for x in a.values() if x['d'] not in codes])
print('other 率', sum(x['d']=='other' for x in a.values())/len(a))
print(collections.Counter(x['k'] for x in a.values()).most_common())
print(collections.Counter(x['ai'] for x in a.values()).most_common())
print(collections.Counter(parent.get(x['d']) for x in a.values()).most_common())
print('tags/repo', sum(len(x['t']) for x in a.values())/len(a))
print('--- 一级分歧')
for n in common:
    if parent.get(a[n]['d'])!=parent.get(b[n]['d']): print(n[:38].ljust(38), a[n]['k'],a[n]['d'], '|', b[n]['k'],b[n]['d'], '|', a[n]['s'])
