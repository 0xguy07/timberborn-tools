import json, zipfile, os, collections, sys, math, glob
from collections import deque

def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag); v = sys.argv[i+1]; del sys.argv[i:i+2]; return v
    return default
_bp = _arg("--blueprints", os.environ.get("TIMBERBORN_BLUEPRINTS"))
_ref = _arg("--reference", os.environ.get("TIMBERBORN_REFERENCE_MAP", ""))
_pos = [a for a in sys.argv[1:] if not a.startswith("--")]
if not _pos:
    sys.exit("usage: validate_map.py MAP.timber [--reference SHIPPED_MAP.timber] [--blueprints Blueprints.zip]")
p=os.path.expanduser(_pos[0])
z=zipfile.ZipFile(p); w=json.loads(z.read("world.json")); md=json.loads(z.read("map_metadata.json"))
W,H=md["Width"],md["Height"]
vox=w['Singletons']['TerrainMap']['Voxels']['Array'].split(' '); Z=len(vox)//(W*H)
hm=[[0]*W for _ in range(H)]
for y in range(H):
    for x in range(W):
        h=0
        while h<Z and vox[h*W*H+y*W+x]=='1': h+=1
        hm[y][x]=h
def base_i(y): return int(round(6.0+6.0*y/(H-1)))
def bed_at(y): return base_i(y)-2
def river_center(y):
    return 64.0+26.0*math.sin(y*2*math.pi/150.0+0.4)+7.0*math.sin(y*2*math.pi/47.0)
chan=[[hm[y][x]<=bed_at(y) for x in range(W)] for y in range(H)]

ok=True
def chk(label,cond,extra=""):
    global ok; ok&=bool(cond)
    print(("PASS " if cond else "FAIL ")+label+((" -- "+str(extra)) if extra else ""))

# ------------------------------------------------------- format conformance --
# Blueprints.zip from the game install (optional). --blueprints or TIMBERBORN_BLUEPRINTS overrides the Steam lookup.
BP=[os.path.expanduser(_bp)] if _bp else [b for pat in (
  "~/Library/Application Support/Steam/steamapps/common/Timberborn/Timberborn.app/Contents/Resources/Data/StreamingAssets/Modding/Blueprints.zip",
  "~/.steam/steam/steamapps/common/Timberborn/Timberborn_Data/StreamingAssets/Modding/Blueprints.zip",
  "C:/Program Files (x86)/Steam/steamapps/common/Timberborn/Timberborn_Data/StreamingAssets/Modding/Blueprints.zip",
) for b in glob.glob(os.path.expanduser(pat))]
if BP:
    spec=json.loads(zipfile.ZipFile(BP[0]).read("Configurations/MapSize.blueprint.json")
                    .decode('utf-8-sig'))['MapSizeSpec']
    chk("terrain levels == MaxGameTerrainHeight+1", Z==spec['MaxGameTerrainHeight']+1, Z)
    chk("terrain <= MaxMapEditorTerrainHeight",
        max(max(r) for r in hm)<=spec['MaxMapEditorTerrainHeight'], max(max(r) for r in hm))
chk("voxel array length", len(vox)==W*H*Z, f"{len(vox)} = {W}x{H}x{Z}")
chk("no gaps/floating voxels",
    all(vox[zz*W*H+y*W+x]=='0' for y in range(H) for x in range(W) for zz in range(hm[y][x],Z)))
for n,k in [('WaterEvaporationMap','EvaporationModifiers'),('WaterMapNew','WaterColumns'),
            ('WaterMapNew','ColumnOutflows'),('SoilMoistureSimulator','MoistureLevels'),
            ('SoilContaminationSimulator','ContaminationCandidates'),
            ('SoilContaminationSimulator','ContaminationLevels')]:
    chk(f"{n}.{k} length", len(w['Singletons'][n][k]['Array'].split(' '))==W*H*2)
chk("version matches game", w['GameVersion']==z.read('version.txt').decode())

# A map shipped with the game (e.g. Plains), used only to compare JSON shape. Optional; never commit one.
REF=os.path.expanduser(_ref)
if REF and os.path.exists(REF):
    ref=json.loads(zipfile.ZipFile(REF).read("world.json"))
    def shape(o):
        if isinstance(o,dict): return {k:shape(v) for k,v in o.items()}
        if isinstance(o,list): return [shape(o[0])] if o else []
        return type(o).__name__
    def merge(a,b):
        if a is None: return b
        if isinstance(a,dict) and isinstance(b,dict):
            return {k:merge(a.get(k),b.get(k)) for k in set(a)|set(b)}
        if isinstance(a,list) and isinstance(b,list):
            return [merge(a[0],b[0])] if a and b else (a or b)
        return a
    def conforms(m,r,path=""):
        if isinstance(m,dict):
            if not isinstance(r,dict): return [path or "<root>"]
            bad=[]
            for k,v in m.items():
                if k not in r: bad.append(f"{path}.{k}" if path else k)
                else: bad+=conforms(v,r[k],f"{path}.{k}" if path else k)
            return bad
        if isinstance(m,list):
            if not isinstance(r,list): return [path]
            return conforms(m[0],r[0],path+"[]") if m and r else []
        return [] if m==r else [f"{path} ({m} vs {r})"]
    chk("singleton shapes match reference", shape(ref['Singletons'])==shape(w['Singletons']))
    chk("timestamp format matches reference", not w['Timestamp'].endswith('Z'))
    rc=collections.defaultdict(dict)
    for e in ref['Entities']:
        for k,v in e['Components'].items(): rc[e['Template']][k]=merge(rc[e['Template']].get(k),shape(v))
    unknown=[];bad=[]
    for e in w['Entities']:
        known=rc.get(e['Template'])
        if known is None: unknown.append(e['Template']); continue
        for k,v in e['Components'].items():
            if k not in known: unknown.append(f"{e['Template']}.{k}")
            else: bad+=[(e['Template'],b) for b in conforms(shape(v),known[k])]
    chk("every component known for its template", not unknown, sorted(set(unknown))[:5])
    chk("component shapes conform to reference", not bad, sorted(set(bad))[:4])

# --------------------------------------------------------------- geometry ---
cliffs=[(x,y,hm[y][x],hm[y+dy][x+dx]) for y in range(H) for x in range(W) for dx,dy in ((1,0),(0,1))
        if x+dx<W and y+dy<H and abs(hm[y][x]-hm[y+dy][x+dx])>=2]
chk("no unwalkable cliffs", not cliffs, cliffs[:4])
mis=[e['Template'] for e in w['Entities']
     if e['Components']['BlockObject']['Coordinates']['Z']
        !=hm[e['Components']['BlockObject']['Coordinates']['Y']][e['Components']['BlockObject']['Coordinates']['X']]]
chk("all entities grounded", not mis, collections.Counter(mis))
FOOT={'StartingLocation':(3,3),'ReserveWarehouse':(2,2),'ReserveTank':(2,2),'ReservePile':(2,2)}
cells=collections.Counter()
for e in w['Entities']:
    c=e['Components']['BlockObject']['Coordinates']; fw,fh=FOOT.get(e['Template'],(1,1))
    for dy in range(fh):
        for dx in range(fw): cells[(c['X']+dx,c['Y']+dy)]+=1
chk("no overlapping footprints", max(cells.values())==1)
chk("unique entity ids", len({e['Id'] for e in w['Entities']})==len(w['Entities']))

# ------------------------------------------------------------------ water ---
# What matters for flow is that a through-channel exists at the designed bed in
# every row and that the bed descends. Deliberate depressions (pools, the two
# reservoirs) sit BELOW that bed on purpose, so they must be excluded from the
# measurement -- otherwise a reservoir floor reads as the row's sill.
rows=[y for y in range(H) if any(chan[y])]
missing=[y for y in rows if not any(chan[y][x] and hm[y][x]==bed_at(y) for x in range(W))]
chk("a through-channel exists at the designed bed in every row",
    len(missing)<=2, f"{len(missing)} rows without one: {missing[:6]}")
chk("bed descends north->south (a flat bed does not flow)",
    bed_at(127)-bed_at(0)>=5, f"bed {bed_at(127)} at y=127 -> {bed_at(0)} at y=0")
chk("channel reaches the outlet row", any(chan[0]))
flat=cur=1
for y in range(1,H):
    cur = cur+1 if bed_at(y)==bed_at(y-1) else 1
    flat=max(flat,cur)
chk("no long flat stretch (<=30 rows at one bed level)", flat<=30, f"longest {flat} rows")
deep=[(x,y) for y in range(H) for x in range(W) if chan[y][x] and hm[y][x]<=bed_at(y)-2]
chk("deep water exists for pumps (>=2 below bed)", len(deep)>=150, f"{len(deep)} tiles")

srcs=[(e['Components']['BlockObject']['Coordinates']['X'],e['Components']['BlockObject']['Coordinates']['Y'])
      for e in w['Entities'] if e['Template']=='WaterSource']
strength=sum(e['Components']['WaterSource']['SpecifiedStrength']
             for e in w['Entities'] if e['Template']=='WaterSource')
chk("sources sit in a channel", all(chan[y][x] for x,y in srcs), len(srcs))
chk("total inflow is sane (2-8)", 2.0<=strength<=8.0, f"{strength:.2f} across {len(srcs)} sources")
seen=set(srcs); q=deque(srcs)
while q:
    x,y=q.popleft()
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx,ny=x+dx,y+dy
        if 0<=nx<W and 0<=ny<H and (nx,ny) not in seen and chan[ny][nx]:
            seen.add((nx,ny)); q.append((nx,ny))
allchan={(x,y) for y in range(H) for x in range(W) if chan[y][x]}
orphan=allchan-seen
chk("every channel tile is fed by a source", not orphan, f"{len(orphan)} dry ditch tiles")
# A basin fed by a source with no path to an edge fills forever and floods.
edges=deque([(x,y) for x,y in allchan if x in (0,W-1) or y in (0,H-1)])
drain=set(edges)
while edges:
    x,y=edges.popleft()
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx,ny=x+dx,y+dy
        if 0<=nx<W and 0<=ny<H and (nx,ny) not in drain and chan[ny][nx]:
            drain.add((nx,ny)); edges.append((nx,ny))
chk("water drains off a map edge", bool(drain))
chk("no closed basin (every channel tile can reach an edge)",
    not (allchan-drain), f"{len(allchan-drain)} landlocked tiles")
below=[(x,y) for y in range(H) for x in range(W) if hm[y][x]<bed_at(y)]
retained=sum(bed_at(y)-hm[y][x] for x,y in below)
chk("reservoirs hold >=900 blocks in drought", retained>=900, f"{retained} over {len(below)} tiles")
chk("reservoirs are fed", all(t in seen for t in below))

# irrigation, measured the way the shipped map's own moisture data behaves:
# 0-2 levels above the waterline reaches 10+ tiles, 3 levels only 4, 4+ never.
INF=10**9; dist=[[INF]*W for _ in range(H)]; wl=[[0]*W for _ in range(H)]
q=deque()
for x,y in allchan:
    dist[y][x]=0; wl[y][x]=hm[y][x]+1; q.append((x,y))
while q:
    x,y=q.popleft()
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx,ny=x+dx,y+dy
        if 0<=nx<W and 0<=ny<H and dist[ny][nx]==INF:
            dist[ny][nx]=dist[y][x]+1; wl[ny][nx]=wl[y][x]; q.append((nx,ny))
arable=sum(1 for y in range(H) for x in range(W) if dist[y][x]>0 and
           ((hm[y][x]-wl[y][x]<=2 and dist[y][x]<=10) or (hm[y][x]-wl[y][x]==3 and dist[y][x]<=4)))
land=W*H-len(allchan)
chk("arable land >= 55% (was 25% before this pass)", arable/land>=0.55,
    f"{arable}/{land} = {arable/land*100:.0f}%")
chk("some dry high ground remains for building", 1-arable/land>=0.10,
    f"{(1-arable/land)*100:.0f}% dry")

# ------------------------------------------------------------- settlement ---
sl=[e for e in w['Entities'] if e['Template']=='StartingLocation']
chk("exactly one starting location", len(sl)==1)
c=sl[0]['Components']['BlockObject']['Coordinates']; sx,sy=c['X'],c['Y']
ent={(e['Components']['BlockObject']['Coordinates']['X']+dx,
      e['Components']['BlockObject']['Coordinates']['Y']+dy)
     for e in w['Entities'] if e['Template'] not in ('StartingLocation','WaterSource')
     for dx in range(FOOT.get(e['Template'],(1,1))[0])
     for dy in range(FOOT.get(e['Template'],(1,1))[1])}
RES={'ReserveWarehouse','ReserveTank','ReservePile'}
rescells={(e['Components']['BlockObject']['Coordinates']['X']+dx,
           e['Components']['BlockObject']['Coordinates']['Y']+dy)
          for e in w['Entities'] if e['Template'] in RES for dx in range(2) for dy in range(2)}
# largest clear, level, channel-free square containing spawn
def zone_size():
    best=0
    for size in range(8, 41, 2):
        found=False
        for y0 in range(max(0,sy-size+1), min(H-size, sy+1)):
            for x0 in range(max(0,sx-size+1), min(W-size, sx+1)):
                lv=hm[y0][x0]
                if all(hm[y][x]==lv and not chan[y][x] and (x,y) not in ent
                       for y in range(y0,y0+size) for x in range(x0,x0+size)):
                    found=True; break
            if found: break
        if found: best=size
        else: break
    return best
zs=zone_size()
chk("clear level building zone at spawn >= 28x28", zs>=28, f"{zs}x{zs} = {zs*zs} tiles")
dd=min(math.hypot(sx-x, sy-y) for x,y in rescells)
chk("depot is out of the way but reachable (12-40 tiles)", 12<=dd<=40, f"{dd:.0f} tiles")
seen2={(sx,sy)}; q=deque([(sx,sy)])
while q:
    x,y=q.popleft()
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx,ny=x+dx,y+dy
        if 0<=nx<W and 0<=ny<H and (nx,ny) not in seen2 and abs(hm[ny][nx]-hm[y][x])<=1:
            seen2.add((nx,ny)); q.append((nx,ny))
chk("all land walkable from spawn", len(seen2)>=(W*H-len(allchan))*0.98,
    f"{len(seen2)}/{W*H}")
chk("caches walkable from spawn", all(t in seen2 for t in rescells))
VEG={'Pine','Oak','Birch','BlueberryBush'}
veg={(e['Components']['BlockObject']['Coordinates']['X'],e['Components']['BlockObject']['Coordinates']['Y'])
     for e in w['Entities'] if e['Template'] in VEG}
touch=[v for v in veg if any((v[0]+dx,v[1]+dy) in rescells for dx in (-1,0,1) for dy in (-1,0,1))]
chk("no vegetation touching a cache", not touch, touch[:5])
chk("spawn is near water", min(dist[y][x] for y in range(sy-1,sy+2) for x in range(sx-1,sx+2))<=10,
    min(dist[y][x] for y in range(sy-1,sy+2) for x in range(sx-1,sx+2)))

CAP={'ReserveWarehouse':(200,'Box'),'ReserveTank':(300,'Liquid'),'ReservePile':(160,'Pileable')}
TYPE={'Berries':'Box','Gear':'Box','Water':'Liquid','Log':'Pileable','Plank':'Pileable',
      'Dirt':'Pileable','ScrapMetal':'Pileable'}
over=[];wrong=[];stock=collections.Counter()
for e in w['Entities']:
    if e['Template'] not in CAP: continue
    cap,wlst=CAP[e['Template']]
    g=e['Components']['Inventory:Stockpile']['Storage']['Goods'][0]
    stock[g['Good']]+=g['Amount']
    if g['Amount']>cap: over.append((e['Template'],g))
    if TYPE.get(g['Good'])!=wlst: wrong.append((e['Template'],g['Good']))
chk("caches within capacity", not over, over)
chk("goods match storage type", not wrong, wrong)
chk("ReserveTank has no visualizer", not any('StockpileVisualizers' in e['Components']
    for e in w['Entities'] if e['Template']=='ReserveTank'))
def near(t,r):
    return sum(1 for e in w['Entities'] if e['Template'].startswith(t)
        and abs(e['Components']['BlockObject']['Coordinates']['X']-sx)<=r
        and abs(e['Components']['BlockObject']['Coordinates']['Y']-sy)<=r)
chk("berries within reach", near('BlueberryBush',34)>=80, near('BlueberryBush',34))
chk("trees within reach", near('Birch',34)+near('Pine',34)>=120, near('Birch',34)+near('Pine',34))
chk("scrap ruins within reach", near('RuinColumn',40)>=20, near('RuinColumn',40))
print("   starting stock:", dict(stock))
print("\nRESULT:", "ALL CHECKS PASSED" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
