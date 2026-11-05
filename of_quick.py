import json,glob,os,sys,math,statistics as st,collections,bisect
sys.path.insert(0,'/home/claude/edgehog'); import score
FS=sorted(glob.glob('/mnt/user-data/uploads/edgehog/data/raw/pm_trades_*.json'),key=os.path.getsize,reverse=True)
def load(f):
    rows=json.load(open(f))['rows']
    cnt=collections.Counter(r['asset'] for r in rows)
    assets=list(cnt)
    if len(assets)!=2: return None
    A=assets[0]
    out=[]
    for r in rows:
        p,s,t=r.get('price'),r.get('size'),r.get('timestamp')
        if p is None or s is None or t is None: continue
        sd=1 if r['side']=='BUY' else -1
        if r['asset']==A: d,y=sd,p
        else: d,y=-sd,1-p
        if not (0.03<y<0.97): continue
        out.append((float(t),d,float(y),float(s),r.get('proxyWallet')))
    out.sort()
    return out
def bars(tr,w=60):
    t0=tr[0][0]; B=collections.OrderedDict()
    lastb=lasts=None
    for t,d,y,s,_ in tr:
        k=int((t-t0)//w); b=B.setdefault(k,{'buy':0.,'sell':0.})
        if d>0: b['buy']+=s; lastb=y
        else: b['sell']+=s; lasts=y
        b['mid']=(lastb+lasts)/2 if lastb is not None and lasts is not None else None
    n=max(B)+1; out=[]; mid=None
    for k in range(n):
        b=B.get(k,{'buy':0.,'sell':0.,'mid':None})
        if b.get('mid') is not None: mid=b['mid']
        out.append((b['buy'],b['sell'],mid))
    return out
res={'fut':[], 'imp':[], 'big':[]}
qbins=collections.defaultdict(list)
for f in FS:
    tr=load(f)
    if not tr or len(tr)<200: continue
    mk=os.path.basename(f)
    bs=bars(tr)
    vols=[b[0]+b[1] for b in bs if b[0]+b[1]>0]
    if len(vols)<30: continue
    avg=st.mean(vols)
    for i in range(1,len(bs)-5):
        bu,se,m=bs[i]; m0=bs[i-1][2]; m5=bs[i+5][2]
        if bu+se==0 or m is None or m0 is None or m5 is None: continue
        nd=(bu-se)/avg
        sgn=1 if bu>se else -1
        res['imp'].append((sgn*(m-m0),1.0,mk))
        res['fut'].append((sgn*(m5-m),1.0,mk))
        q=0 if nd<-1 else 1 if nd<-0.2 else 2 if nd<0.2 else 3 if nd<1 else 4
        qbins[q].append(((m5-m),1.0,mk))
    # large prints
    sizes=sorted(s*y for t,d,y,s,_ in tr)
    thr=max(500,sizes[int(.95*len(sizes))])
    ts=[x[0] for x in tr]
    def mid_at(tau):
        lb=ls=None; i=bisect.bisect_right(ts,tau)-1
        while i>=0 and ts[i]>tau-300 and (lb is None or ls is None):
            if tr[i][1]>0 and lb is None: lb=tr[i][2]
            elif tr[i][1]<0 and ls is None: ls=tr[i][2]
            i-=1
        return (lb+ls)/2 if lb is not None and ls is not None else None
    for t,d,y,s,_ in tr:
        if s*y<thr: continue
        a=mid_at(t+10); b=mid_at(t+300); pre=mid_at(t-1)
        if a is None or b is None or pre is None: continue
        res['big'].append(((d*(b-a)),1.0,mk))
        res.setdefault('bigimp',[]).append((d*(a-pre),1.0,mk))
def show(name,it):
    n,G,m,se,_=score.cstats(it); print(f"{name:<58} {m*100:+.2f} ±{se*100:.2f} sz.pont  (n={n}, piac={G}, medián {st.median(v for v,_,_ in it)*100:+.2f})")
print("Piacok:",len({x[2] for x in res['fut']}))
show("Delta-bar saját percében: középár-mozgás delta irányában",res['imp'])
show("Delta-bar UTÁN 5 percig: középár-mozgás delta irányában",res['fut'])
for q in range(5): show(f"  delta-kvintilis {q} (0=erős eladás..4=erős vétel): jövő 5p mozgás",qbins[q])
show("Nagy kötés (top 5%, ≥$500): +10mp-ig (saját hatás)",res['bigimp'])
show("Nagy kötés: +10mp → +5p, a kötés irányában (folytatás>0, visszafordulás<0)",res['big'])
