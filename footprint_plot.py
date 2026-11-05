import sys, json, collections, math
sys.path.insert(0,'/tmp/claude-0/of')
from of import load
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
f='/mnt/user-data/uploads/edgehog/data/raw/pm_trades_0x009d773159b72d05.json'
tr=load(f)
# pick busiest 40-min window
W=120; t0=tr[0][0]
cnt=collections.Counter(int((t-t0)//W) for t,*_ in tr)
best=max(cnt, key=lambda k: sum(cnt.get(k+j,0) for j in range(20)))
lo=t0+best*W; hi=lo+20*W
win=[x for x in tr if lo<=x[0]<hi]
cells=collections.defaultdict(lambda:[0.,0.]); bars=collections.defaultdict(lambda:[0.,0.])
for t,d,y,s,_ in win:
    b=int((t-lo)//W); lv=round(y,2)
    cells[(b,lv)][0 if d<0 else 1]+=s; bars[b][0 if d<0 else 1]+=s
levels=sorted({lv for _,lv in cells})
nb=20
fig,(ax,ax2)=plt.subplots(2,1,figsize=(16,10),gridspec_kw={'height_ratios':[3.2,1]},sharex=True)
fig.patch.set_facecolor('#111418'); 
for a in (ax,ax2): a.set_facecolor('#111418'); a.tick_params(colors='#cfd6de'); [s.set_color('#3a414a') for s in a.spines.values()]
vmax=max(abs(b-s) for s,b in cells.values()) or 1
for (b,lv),(se,bu) in cells.items():
    dl=bu-se; a=min(1,abs(dl)/vmax)**0.6
    col=(0.15,0.75,0.45,0.15+0.7*a) if dl>0 else (0.9,0.3,0.3,0.15+0.7*a)
    ax.add_patch(Rectangle((b-0.48,lv-0.0048),0.96,0.0096,color=col,lw=0))
    ax.text(b,lv,f"{se/1000:.1f}k × {bu/1000:.1f}k" if max(se,bu)>=1000 else f"{se:.0f} × {bu:.0f}",ha='center',va='center',fontsize=6.5,color='#eef2f5')
# big prints
sizes=sorted(s*y for t,d,y,s,_ in tr); thr=max(500,sizes[int(.97*len(sizes))])
for t,d,y,s,_ in win:
    if s*y>=thr:
        ax.scatter((t-lo)/W-0.5+0.02,y,s=min(400,s*y/40),facecolors='none',edgecolors='#7fd1ff' if d>0 else '#ffb36b',lw=1.2,zorder=5)
ax.set_ylim(min(levels)-0.01,max(levels)+0.01); ax.set_xlim(-0.6,nb-0.4)
ax.set_ylabel('ár (az első kimenet, $)',color='#cfd6de')
ax.set_title(f'Polymarket élő piac – footprint 2 perces gyertyákkal (eladó × vevő taker-mennyiség), {len(win)} kötés; körök: nagy kötések',color='#eef2f5',fontsize=12,loc='left')
dl=[bars[b][1]-bars[b][0] for b in range(nb)]
ax2.bar(range(nb),dl,color=['#2fbf72' if v>0 else '#e05050' for v in dl])
cd=[sum(dl[:i+1]) for i in range(nb)]
ax3=ax2.twinx(); ax3.plot(range(nb),cd,color='#e8c547',lw=1.8); ax3.tick_params(colors='#e8c547'); [s.set_color('#3a414a') for s in ax3.spines.values()]
ax2.set_ylabel('delta / gyertya',color='#cfd6de'); ax3.set_ylabel('kumulatív delta',color='#e8c547')
ax2.set_xticks(range(0,nb,2)); ax2.set_xticklabels([f"{2*i}′" for i in range(0,nb,2)]); ax2.set_xlabel('perc',color='#cfd6de')
plt.tight_layout(); plt.savefig('/tmp/claude-0/of/footprint.png',dpi=130,facecolor=fig.get_facecolor())
print(len(win), len(levels), thr)
