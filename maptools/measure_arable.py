import json, zipfile, os, sys
from collections import deque
if len(sys.argv)<2: sys.exit("usage: measure_arable.py MAP.timber")
p=os.path.expanduser(sys.argv[1])
w=json.loads(zipfile.ZipFile(p).read("world.json"))
md=json.loads(zipfile.ZipFile(p).read("map_metadata.json"))
W,H=md["Width"],md["Height"]
vox=w['Singletons']['TerrainMap']['Voxels']['Array'].split(' '); Z=len(vox)//(W*H)
hm=[[0]*W for _ in range(H)]
for y in range(H):
    for x in range(W):
        h=0
        while h<Z and vox[h*W*H+y*W+x]=='1': h+=1
        hm[y][x]=h
def base_i(y): return int(round(6.0+6.0*y/(H-1)))
# channel = anything at or below the local bed; assume it settles ~1 deep
chan=[(x,y) for y in range(H) for x in range(W) if hm[y][x]<=base_i(y)-2]
INF=10**9
dist=[[INF]*W for _ in range(H)]; wl=[[0]*W for _ in range(H)]
q=deque()
for x,y in chan:
    dist[y][x]=0; wl[y][x]=hm[y][x]+1; q.append((x,y))
while q:
    x,y=q.popleft()
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx,ny=x+dx,y+dy
        if 0<=nx<W and 0<=ny<H and dist[ny][nx]==INF:
            dist[ny][nx]=dist[y][x]+1; wl[ny][nx]=wl[y][x]; q.append((nx,ny))
arable=dry=0
for y in range(H):
    for x in range(W):
        if dist[y][x]==0: continue
        rise=hm[y][x]-wl[y][x]
        d=dist[y][x]
        if (rise<=2 and d<=10) or (rise==3 and d<=4): arable+=1
        else: dry+=1
land=W*H-len(chan)
print(f"{os.path.basename(p)}")
print(f"  water tiles : {len(chan):6d}")
print(f"  land tiles  : {land:6d}")
print(f"  ARABLE      : {arable:6d}  ({arable/land*100:.0f}% of land)")
print(f"  dry         : {dry:6d}  ({dry/land*100:.0f}% of land)")

# coarse map of where the dry ground is (16x16 blocks)
print("\ndry-land density by 16x16 block (north at top, % of block that is dry land):")
for by in range(H-16, -1, -16):
    row=""
    for bx in range(0, W, 16):
        tot=d=0
        for y in range(by, by+16):
            for x in range(bx, bx+16):
                if dist[y][x]==0: continue
                tot+=1
                rise=hm[y][x]-wl[y][x]
                if not ((rise<=2 and dist[y][x]<=10) or (rise==3 and dist[y][x]<=4)): d+=1
        row += f"{(d/tot*100 if tot else 0):>5.0f}"
    print(f"  y{by:>3}-{by+15:<3}{row}")
print("        " + "".join(f"{('x'+str(bx)):>5}" for bx in range(0, W, 16)))
