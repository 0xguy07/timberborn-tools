#!/usr/bin/env python3
"""Beginner-friendly Timberborn 1.0 practice map.

Design targets, all asserted by validate_map.py:
  * the valley slopes north->south so the river actually flows
  * a braided water network, so most of the map is within irrigation range
  * a large clear, level building zone around spawn
  * the supply depot pushed well clear of that zone
"""
import json, math, random, uuid, zipfile, io, os, sys
from collections import deque

random.seed(20260830)
W = H = 128

# Vertical size is global, from Blueprints.zip Configurations/MapSize.blueprint.json
# MapSizeSpec.MaxGameTerrainHeight (22) + 1. Wrong value => IndexOutOfRangeException
# in MapIndexService.Unpack3D on load, with no in-game error.
MAX_GAME_TERRAIN_HEIGHT = 22
Z = MAX_GAME_TERRAIN_HEIGHT + 1
MAX_EDITOR_HEIGHT = 16

# Measured from the shipped Plains map's own moisture data: land 0-2 levels above
# the waterline is irrigated out to 10+ tiles, 3 levels only within 4 tiles, and
# 4+ levels is permanently dry. So arable land is set by how widely water is
# spread, not by how much flat ground exists.
BASE_SOUTH, BASE_DROP, BED_BELOW = 6.0, 6.0, 2
def datum(y):  return BASE_SOUTH + BASE_DROP * y / (H - 1)
def base_i(y): return int(round(datum(y)))
def bed_at(y): return base_i(y) - BED_BELOW
def rnd(v):    return math.floor(v + 0.5)      # monotone; round() banks to even

GAME_VERSION = "1.0.13.1-b769e88-sm"

# ------------------------------------------------------------ water network --
channel = [[False] * W for _ in range(H)]
bed_h   = [[0] * W for _ in range(H)]

RESERVED = []          # rectangles kept free of water: settlement + depot yard
# Levelling a plateau raises its rim, so water must stay this far from a zone or
# the rim becomes a 2-block cliff. Every carve after zone selection obeys it.
ZONE_MARGIN = 4
def reserved(x, y, m=ZONE_MARGIN):
    return any(rx-m <= x < rx+rw+m and ry-m <= y < ry+rh+m for rx, ry, rw, rh in RESERVED)

def path_hits_reserved(pts):
    return any(reserved(int(px), int(py), 4) for px, py in pts)

def carve(pts, hw_fn, depth_fn=None):
    for i, (px, py) in enumerate(pts):
        t = i / max(1, len(pts) - 1)
        hw = hw_fn(t, px, py)
        for yy in range(int(py - hw - 1), int(py + hw + 2)):
            for xx in range(int(px - hw - 1), int(px + hw + 2)):
                if not (0 <= xx < W and 0 <= yy < H):
                    continue
                if math.hypot(xx - px, yy - py) > hw or reserved(xx, yy):
                    continue
                b = depth_fn(xx, yy) if depth_fn else bed_at(yy)
                if not channel[yy][xx] or b < bed_h[yy][xx]:
                    channel[yy][xx], bed_h[yy][xx] = True, b

def bezier(p0, p1, p2, n=400):
    return [((1-t)**2*p0[0] + 2*(1-t)*t*p1[0] + t*t*p2[0],
             (1-t)**2*p0[1] + 2*(1-t)*t*p1[1] + t*t*p2[1])
            for t in (i/(n-1) for i in range(n))]

# main river: a wide sweeping meander so its moist band covers much more ground
def river_center(y):
    return 64.0 + 26.0 * math.sin(y * 2*math.pi/150.0 + 0.4) \
                +  7.0 * math.sin(y * 2*math.pi/47.0)

CHOKE_Y = 34          # narrow spot: the cheap early dam site
def river_hw(y):
    hw = 3.1 + 0.9 * math.sin(y * 2*math.pi/63.0)
    hw += 2.2 * math.exp(-((y - 96) / 9.0) ** 2)     # backwater lagoon
    hw += 2.0 * math.exp(-((y - 58) / 8.0) ** 2)     # backwater lagoon
    hw -= 1.7 * math.exp(-((y - CHOKE_Y) / 5.0) ** 2)  # choke point for damming
    return hw

main = [(river_center(127 - i * 127 / 599), 127 - i * 127 / 599) for i in range(600)]
carve(main, lambda t, px, py: river_hw(py))

# tributaries: each joins the main channel, spreading irrigation into the corners
# Each entry is a quadratic Bezier (start, control, join). Entries whose start
# sits on a map edge get water sources; the rest are distributaries that carry
# water back out, so they must run downhill from their junction.
# (start, control, junction row). The junction row is a hint: route() slides it
# along the river if the straight path would cross a reserved zone.
TRIBS = [((14, 125), (26, 108), 94), ((122, 112), (104, 96), 78),
         ((4, 84),   (20, 74),  66), ((124, 52),  (100, 44), 30),
         ((112, 126), (100, 112), 104), ((126, 72), (112, 66), 58),
         ((2, 58),   (16, 52),  44)]
# distributaries: start on the river and drain toward a lower edge (no source)
DISTRIBS = [((river_center(20), 20), (78, 12), (70, 2)),
            ((river_center(26), 26), (30, 14), (8, 6)),
            ((river_center(22), 22), (104, 12), (122, 4))]
# reservoir: floor 3 below the inlet sill, so it keeps water when sources stop
LAKE_CX, LAKE_CY, LAKE_RX, LAKE_RY = 30.0, 38.0, 11.0, 8.0
LAKE_FLOOR = bed_at(LAKE_CY) - 3
for y in range(H):
    for x in range(W):
        a = math.atan2(y - LAKE_CY, x - LAKE_CX)
        r = 1.0 + 0.11*math.sin(3*a + 0.7) + 0.07*math.sin(5*a + 2.1)
        d = math.hypot((x - LAKE_CX)/(LAKE_RX*r), (y - LAKE_CY)/(LAKE_RY*r))
        b = None
        if d <= 0.55:  b = LAKE_FLOOR
        elif d <= 0.78: b = LAKE_FLOOR + 1
        elif d <= 1.0:  b = LAKE_FLOOR + 2
        elif d <= 1.2:  b = bed_at(y)
        if b is not None and (not channel[y][x] or b < bed_h[y][x]):
            channel[y][x], bed_h[y][x] = True, b
carve(bezier((LAKE_CX + 6, LAKE_CY + 2), (46, 40), (river_center(42), 42)),
      lambda t, px, py: 2.2)

# --------------------------------------------------------------- elevation --
def hills(x, y):
    h = 0.0
    for cx, cy, r, amp in [(16, 108, 22, 3.0), (110, 20, 22, 3.0),
                           (114, 112, 18, 2.5), (12, 16, 16, 2.0)]:
        d = math.hypot(x - cx, y - cy) / r
        if d < 1.0:
            h += amp * (math.cos(d*math.pi) + 1.0) / 2.0
    return h

# Banks derive FROM the water: a cone rising one level per tile away from every
# channel tile. That field and the land field are both 1-Lipschitz, so their
# minimum is too -- which is what guarantees no 2-block cliffs anywhere.
INF = 10**9
def build_cone():
    c = [[INF]*W for _ in range(H)]
    q = deque()
    for y in range(H):
        for x in range(W):
            if channel[y][x]:
                c[y][x] = bed_h[y][x]; q.append((x, y))
    while q:
        x, y = q.popleft()
        v = c[y][x] + 1
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = x+dx, y+dy
                if 0 <= nx < W and 0 <= ny < H and v < c[ny][nx]:
                    c[ny][nx] = v; q.append((nx, ny))
    return c

def build_heights(c):
    return [[max(0, min(MAX_EDITOR_HEIGHT,
                        rnd(min(datum(y) + hills(x, y), float(c[y][x])))))
             for x in range(W)] for y in range(H)]

cone = build_cone()
height = build_heights(cone)

# ------------------------------------------- build zone and depot placement --
BUILD = 32          # clear, level building area around spawn
YARD  = 24          # supply depot yard: 5x5 pads at a 5-tile pitch

def window_ok(x0, y0, size):
    """Channel-free including a margin, and shallow enough that levelling it is
    a small cut/fill. The margin matters: flatten a plateau hard against a
    channel and the rim becomes a 2-block cliff that nothing can walk."""
    m = ZONE_MARGIN
    for y in range(y0 - m, y0 + size + m):
        for x in range(x0 - m, x0 + size + m):
            if not (0 <= x < W and 0 <= y < H) or channel[y][x]:
                return None
    lo, hi = 99, -1
    for y in range(y0, y0 + size):
        for x in range(x0, x0 + size):
            lo = min(lo, height[y][x]); hi = max(hi, height[y][x])
    return (lo, hi) if hi - lo <= 3 else None

def water_dist(x0, y0, size):
    best = INF
    for y in range(y0, y0 + size):
        for x in range(x0, x0 + size):
            if channel[y][x]: return 0
            best = min(best, cone[y][x] - bed_at(y))
    return best

cands = []
for y0 in range(2, H - BUILD - 2, 2):
    for x0 in range(2, W - BUILD - 2, 2):
        r = window_ok(x0, y0, BUILD)
        if not r: continue
        d = water_dist(x0, y0, BUILD)
        if d > 8: continue                       # keep the settlement near water
        cx, cy = x0 + BUILD/2, y0 + BUILD/2
        cands.append((math.hypot(cx - 64, cy - 64), x0, y0, r))
assert cands, "no clear building zone found"
cands.sort()
_, BX, BY, (blo, bhi) = cands[0]
BUILD_LEVEL = rnd((blo + bhi) / 2)

# spawn sits on the water side of the zone; pick it now so the depot can be
# placed near the settlement rather than near the zone's geometric centre
sx, sy = min(((cone[y][x] - bed_at(y), x, y)
              for y in range(BY+3, BY+BUILD-3) for x in range(BX+3, BX+BUILD-3)),
             key=lambda t: t[0])[1:]

yards = []
for y0 in range(2, H - YARD - 2, 2):
    for x0 in range(2, W - YARD - 2, 2):
        # must clear the build zone, but stay adjacent to it: a yard parked far
        # away carves an extra hole in the map and blocks more tributaries
        gap_x = max(BX - (x0 + YARD), x0 - (BX + BUILD), 0)
        gap_y = max(BY - (y0 + YARD), y0 - (BY + BUILD), 0)
        if max(gap_x, gap_y) < 3 or gap_x > 14 or gap_y > 14:
            continue
        r = window_ok(x0, y0, YARD)
        if not r: continue
        d = math.hypot(x0 + YARD/2 - sx, y0 + YARD/2 - sy)
        yards.append((d, x0, y0, r))
assert yards, "no clear depot yard found"
yards.sort()
_, DX, DY, (dlo, dhi) = yards[0]
DEPOT_LEVEL = rnd((dlo + dhi) / 2)

# Reserve the settlement and depot BEFORE the tributary network goes in. Carving
# first and hunting for a gap afterwards fails: a dense enough network leaves no
# clear 24x24 anywhere on the map.
RESERVED.extend([(BX, BY, BUILD, BUILD), (DX, DY, YARD, YARD)])
def route(p0, p1, p2=None, join_y=None):
    """Bend a tributary around the reserved zones rather than dropping it --
    dropping one costs a whole corner of the map its irrigation. Both the
    control point and (for tributaries) the junction row can move."""
    offsets = [(0, 0)]
    for r in (8, 16, 24, 32, 40):
        offsets += [(r,0), (-r,0), (0,r), (0,-r), (r,r), (-r,r), (r,-r), (-r,-r)]
    joins = [p2] if p2 is not None else [
        (river_center(jy), jy) for jy in
        (join_y, join_y-8, join_y+8, join_y-16, join_y+16, join_y-24, join_y+24)
        if 2 <= jy <= H-3]
    for j in joins:
        for ox, oy in offsets:
            pts = bezier(p0, (p1[0]+ox, p1[1]+oy), j)
            if any(not (0 <= px < W and 0 <= py < H) for px, py in pts):
                continue
            if not path_hits_reserved(pts):
                return pts
    return None

_skipped = []
for _p0, _p1, _jy in TRIBS:
    _pts = route(_p0, _p1, join_y=_jy)
    if _pts is None:
        _skipped.append((int(_p0[0]), int(_p0[1]))); continue
    carve(_pts, lambda t, px, py: 1.7 + 0.9 * t)
for _p0, _p1, _p2 in DISTRIBS:
    _pts = route(_p0, _p1, p2=_p2)
    if _pts is None:
        _skipped.append((int(_p0[0]), int(_p0[1]))); continue
    carve(_pts, lambda t, px, py: 1.7 + 0.9 * t)

# A second reservoir in the north-east: guarantees water in that corner and gives
# a second dam/reservoir project. It is centred ON an already-carved tributary,
# never in open ground -- a basin with a source and no outlet fills forever and
# floods the map.
_ne_hosts = [(x, y) for y in range(88, 118) for x in range(88, 118)
             if channel[y][x] and not reserved(x, y, ZONE_MARGIN + 9)]
assert _ne_hosts, "no tributary in the north-east to hang the second reservoir on"
NE_CX, NE_CY = min(_ne_hosts, key=lambda t: math.hypot(t[0]-102, t[1]-102))
NE_CX, NE_CY, NE_R = float(NE_CX), float(NE_CY), 9.0
NE_FLOOR = bed_at(NE_CY) - 3
for y in range(H):
    for x in range(W):
        d = math.hypot(x - NE_CX, y - NE_CY) / NE_R
        b = None
        if d <= 0.6:   b = NE_FLOOR
        elif d <= 0.8: b = NE_FLOOR + 1
        elif d <= 1.0: b = NE_FLOOR + 2
        elif d <= 1.2: b = bed_at(y)
        if b is not None and not reserved(x, y) and (not channel[y][x] or b < bed_h[y][x]):
            channel[y][x], bed_h[y][x] = True, b
# no separate outlet needed: the tributary it sits on already flows through it

# A deep pool at the settlement. Water pumps want 2+ blocks of depth and the two
# big reservoirs are a long walk away; this also holds water through a drought
# right where it is needed. Sited on a live channel, so it drains normally.
_pool = [(x, y) for y in range(H) for x in range(W)
         if channel[y][x] and not reserved(x, y, ZONE_MARGIN + 2)
         and 12 <= math.hypot(x - sx, y - sy) <= 20]
if _pool:
    PCX, PCY = min(_pool, key=lambda t: abs(math.hypot(t[0]-sx, t[1]-sy) - 15))
    PFLOOR = bed_at(PCY) - 3
    for y in range(H):
        for x in range(W):
            d = math.hypot((x - PCX)/7.0, (y - PCY)/5.5)
            b = None
            if d <= 0.6:   b = PFLOOR
            elif d <= 0.8: b = PFLOOR + 1
            elif d <= 1.0: b = PFLOOR + 2
            if b is not None and not reserved(x, y) and (not channel[y][x] or b < bed_h[y][x]):
                channel[y][x], bed_h[y][x] = True, b
else:
    PCX = PCY = None
cone = build_cone()
height = build_heights(cone)

def in_build(x, y, m=0): return BX-m <= x < BX+BUILD+m and BY-m <= y < BY+BUILD+m
def in_yard(x, y, m=0):  return DX-m <= x < DX+YARD+m and DY-m <= y < DY+YARD+m

# Level the two plateaus. Hard-stamping a plateau is NOT enough: its rim becomes
# a 2-block cliff. Instead clamp the terrain between LEVEL-d and LEVEL+d, where d
# is the distance to the zone. Both bounds are 1-Lipschitz and so is the water
# cone, so the clamped result is too -- no cliffs anywhere, by construction.
def zone_dist(x0, y0, size):
    d = [[10**9]*W for _ in range(H)]
    q = deque()
    for y in range(y0, y0+size):
        for x in range(x0, x0+size):
            if 0 <= x < W and 0 <= y < H:
                d[y][x] = 0; q.append((x, y))
    while q:
        x, y = q.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = x+dx, y+dy
                if 0 <= nx < W and 0 <= ny < H and d[y][x]+1 < d[ny][nx]:
                    d[ny][nx] = d[y][x]+1; q.append((nx, ny))
    return d

ZONES = [(zone_dist(BX, BY, BUILD), BUILD_LEVEL), (zone_dist(DX, DY, YARD), DEPOT_LEVEL)]
for y in range(H):
    for x in range(W):
        if channel[y][x]:
            continue
        hi = min([height[y][x]] + [lv + d[y][x] for d, lv in ZONES])
        lo = max([0] + [lv - d[y][x] for d, lv in ZONES])
        height[y][x] = max(0, min(MAX_EDITOR_HEIGHT, max(lo, hi)))

# ----------------------------------------------------------------- voxels ---
voxels = bytearray(b'0' * (W * H * Z))
for y in range(H):
    for x in range(W):
        for z in range(height[y][x]):
            voxels[z*W*H + y*W + x] = 0x31
voxel_str = ' '.join(chr(c) for c in voxels)

# --------------------------------------------------------------- entities ---
entities, occupied = [], set()
def free(x, y, pad=0):
    return all((x+dx, y+dy) not in occupied
               for dy in range(-pad, pad+1) for dx in range(-pad, pad+1))
def take(x, y, w=1, d=1):
    for dy in range(d):
        for dx in range(w): occupied.add((x+dx, y+dy))
def add(template, x, y, z, comps=None, orientation=None):
    b = {"Coordinates": {"X": x, "Y": y, "Z": z}}
    if orientation: b["Orientation"] = orientation
    c = {"BlockObject": b}
    if comps: c.update(comps)
    entities.append({"Id": str(uuid.uuid4()), "Template": template, "Components": c})
ORIENT = [None, "Cw90", "Cw180", "Cw270"]

# spawn was chosen above, before the depot yard, so the two end up close
add("StartingLocation", sx, sy, BUILD_LEVEL, orientation="Cw180")
for dy in range(-2, 5):
    for dx in range(-2, 5): occupied.add((sx+dx, sy+dy))

# --- supply depot: free, pre-stocked caches, 5-tile pitch so paths run easily
RESERVES = [("ReserveTank","Water",300,6), ("ReserveWarehouse","Berries",200,4),
            ("ReservePile","Log",160,4),   ("ReservePile","Plank",160,4),
            ("ReservePile","Dirt",160,2),  ("ReservePile","ScrapMetal",160,2),
            ("ReserveWarehouse","Gear",200,1)]
slots = [(DX+1+c*5, DY+1+r*5) for r in range(5) for c in range(5)]
slots = [s for s in slots
         if all(0 <= s[0]+dx < W and 0 <= s[1]+dy < H
                and height[s[1]+dy][s[0]+dx] == DEPOT_LEVEL
                for dy in range(2) for dx in range(2))]
need = sum(n for *_, n in RESERVES)
assert len(slots) >= need, f"only {len(slots)} depot pads for {need} caches"
si = 0
for template, good, amount, n in RESERVES:
    for _ in range(n):
        gx, gy = slots[si]; si += 1
        comps = {"FixedStockpile": {"FixedGoodId": good},
                 "SingleGoodAllower": {"AllowedGood": good},
                 "Inventory:Stockpile": {"Storage": {"Goods": [{"Good": good, "Amount": amount}]}},
                 "Inventory:ConstructionSite": {"Storage": {"Goods": [{"Good": "ScrapMetal", "Amount": 10}]}}}
        if template != "ReserveTank":      # the tank blueprint has no visualizer
            comps["StockpileVisualizers"] = {"CurrentGood": good}
        take(gx, gy, 2, 2)
        add(template, gx, gy, DEPOT_LEVEL, comps, orientation="Cw180")

# Nothing may stand in a building's access tiles, and the build zone stays empty
# so there is room to actually lay out a settlement.
for y in range(DY-1, DY+YARD+1):
    for x in range(DX-1, DX+YARD+1): occupied.add((x, y))
for y in range(BY, BY+BUILD):
    for x in range(BX, BX+BUILD): occupied.add((x, y))

# --- water sources at the top of every inflow --------------------------------
def add_sources(x0, y0, strength, n_max):
    n = 0
    for y in range(max(0, y0-3), min(H, y0+4)):
        for x in range(max(0, x0-6), min(W, x0+7)):
            if n >= n_max: break
            if channel[y][x] and free(x, y):
                add("WaterSource", x, y, height[y][x],
                    {"WaterSource": {"SpecifiedStrength": strength, "CurrentStrength": 0.0}})
                occupied.add((x, y)); n += 1
    return n
# Total inflow ~4.5. For comparison the shipped 256x256 Plains map runs on 3.25.
add_sources(int(river_center(126)), 126, 0.4, 6)
for (p0, _, _) in TRIBS:
    if p0[1] > 120 or p0[0] < 8 or p0[0] > 120:
        add_sources(int(p0[0]), int(p0[1]), 0.15, 2)
# the NE reservoir needs no source of its own; its host tributary feeds it

# --- resources: pushed outside the build zone so there is room to expand -----
def plantable(x, y):
    return (0 <= x < W and 0 <= y < H and not channel[y][x]
            and height[y][x] >= base_i(y) - 1
            and not in_build(x, y, 1) and not in_yard(x, y, 1))

def scatter(template, count, comps_fn, clusters, spread):
    placed = tries = 0
    while placed < count and tries < count*300:
        tries += 1
        cx, cy = random.choice(clusters)
        x, y = int(round(random.gauss(cx, spread))), int(round(random.gauss(cy, spread)))
        if not plantable(x, y) or not free(x, y): continue
        take(x, y); add(template, x, y, height[y][x], comps_fn()); placed += 1
    return placed

def tree_comps(good, amount, grown_p, extra=None):
    def f():
        c = {"CoordinatesOffsetter": {"Random": True},
             "Yielder:Cuttable": {"Yield": {"Good": good, "Amount": amount}}}
        if random.random() > grown_p:
            c["Growable"] = {"GrowthProgress": round(random.uniform(0.25, 0.95), 6)}
        if extra: c.update(extra)
        return c
    return f

# ring the build zone at a comfortable working distance, not on top of it
def ring(rad, n=8, jitter=0):
    cx, cy = BX + BUILD/2, BY + BUILD/2
    return [(int(cx + rad*math.cos(2*math.pi*i/n + jitter)),
             int(cy + rad*math.sin(2*math.pi*i/n + jitter))) for i in range(n)]

scatter("BlueberryBush", 240, lambda: {
            "CoordinatesOffsetter": {"Random": True},
            "GatherableYieldGrower": {"GrowthProgress": 1.0},
            "Yielder:Gatherable": {"Yield": {"Good": "Berries", "Amount": 3}}},
        ring(24, 10), 6.0)
scatter("Birch", 420, tree_comps("Log", 1, 0.75), ring(28, 8, 0.4), 9.0)
scatter("Pine", 520, tree_comps("Log", 2, 0.7,
        {"Yielder:Gatherable": {"Yield": {"Good": "PineResin", "Amount": 0}}}),
        ring(40, 9, 0.2) + [(30, 100), (98, 90)], 11.0)
scatter("Oak", 340, tree_comps("Log", 8, 0.85),
        ring(52, 9, 0.7) + [(18, 20), (110, 60)], 12.0)

for rcx, rcy in ring(30, 2, 1.1):
    placed = tries = 0
    while placed < 40 and tries < 9000:
        tries += 1
        x, y = int(round(random.gauss(rcx, 5.5))), int(round(random.gauss(rcy, 5.5)))
        if not plantable(x, y) or not free(x, y): continue
        hgt = random.choices(range(1, 9), weights=[26,18,15,11,10,7,7,6])[0]
        take(x, y)
        add(f"RuinColumnH{hgt}", x, y, height[y][x],
            {"Yielder:Ruin": {"Yield": {"Good": "ScrapMetal", "Amount": hgt*15}},
             "RuinModels": {"VariantId": random.choice("ABCDE")}},
            orientation=random.choice(ORIENT))
        placed += 1

# ------------------------------------------------------------- world.json ---
cells2 = W * H * 2
def arr(v, n): return {"Array": ' '.join([v]*n)}
world = {
    "GameVersion": GAME_VERSION,
    "Timestamp": "2026-08-30 12:00:00",
    "Singletons": {
        "MapSize": {"Size": {"X": W, "Y": H}},
        "TerrainMap": {"Voxels": {"Array": voxel_str}},
        "MapThumbnailCameraMover": {"CurrentConfiguration": {
            "Position": {"X": 112.0, "Y": 62.0, "Z": -18.0},
            "Rotation": {"X": 0.234641448, "Y": -0.201924, "Z": 0.0498960651, "W": 0.94956857},
            "ShadowDistance": 150.0}},
        "HazardousWeatherHistory": {"HistoryData": []},
        "WaterEvaporationMap": {"Levels": 2, "EvaporationModifiers": arr("1", cells2)},
        "WaterSimulationMigrator": {"IsMigrated": True},
        "WaterMapNew": {"Levels": 2, "WaterColumns": arr("0", cells2),
                        "ColumnOutflows": arr("0", cells2)},
        "SoilMoistureSimulator": {"Size": 2, "MoistureLevels": arr("0", cells2)},
        "SoilContaminationSimulator": {"Size": 2, "ContaminationCandidates": arr("0", cells2),
                                       "ContaminationLevels": arr("0", cells2)},
        "NumberedEntityNamerService": {"NextNumbers": []},
        "WindService": {"WindStrength": 0.0, "WindDirection": {"X": 0.0, "Y": 0.0},
                        "NextWindChangeTime": 0.0},
    },
    "Entities": entities,
}
metadata = {"Width": W, "Height": H, "MapNameLocKey": "", "MapDescriptionLocKey": "",
    "MapDescription": "A practice valley that slopes north to south so the river "
                      "runs. A braided channel network keeps most of the map "
                      "inside irrigation range, there is a large clear building "
                      "zone at the settlement, and a natural choke point "
                      "downstream makes a cheap first dam.",
    "IsRecommended": False, "IsUnconventional": False, "IsDev": False}

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required for the map thumbnail: pip install Pillow")
img = Image.new("RGB", (W, H)); px = img.load()
tree_at = {(e["Components"]["BlockObject"]["Coordinates"]["X"],
            e["Components"]["BlockObject"]["Coordinates"]["Y"])
           for e in entities if e["Template"] in ("Pine","Oak","Birch")}
res_at = {(e["Components"]["BlockObject"]["Coordinates"]["X"]+dx,
           e["Components"]["BlockObject"]["Coordinates"]["Y"]+dy)
          for e in entities if e["Template"].startswith("Reserve")
          for dx in range(2) for dy in range(2)}
for y in range(H):
    for x in range(W):
        h = height[y][x]
        if channel[y][x]:            c = (30, 80+3*h, 120+3*h)
        elif h < base_i(y):          c = (150, 140, 104)
        else:
            t = min(1.0, max(0.0, (h - base_i(y))/4.0))
            c = (int(104+62*t), int(138+42*t), int(76+42*t))
        if in_build(x, y) and not channel[y][x]: c = (176, 186, 150)
        if (x, y) in tree_at: c = (52, 92, 54)
        if (x, y) in res_at:  c = (206, 150, 70)
        px[x, H-1-y] = c
img = img.resize((512, 512), Image.NEAREST)
buf = io.BytesIO(); img.save(buf, "JPEG", quality=88)

out = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else "Practice Valley.timber"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("map_metadata.json", json.dumps(metadata))
    z.writestr("map_thumbnail.jpg", buf.getvalue())
    z.writestr("version.txt", GAME_VERSION)
    z.writestr("world.json", json.dumps(world))

import collections
print("wrote", out, os.path.getsize(out), "bytes")
print(f"build zone {BUILD}x{BUILD} at ({BX},{BY}) level {BUILD_LEVEL} | spawn ({sx},{sy})")
print(f"depot yard {YARD}x{YARD} at ({DX},{DY}) level {DEPOT_LEVEL} | "
      f"{int(math.hypot(DX+YARD/2-sx, DY+YARD/2-sy))} tiles from spawn")
print(f"water tiles {sum(map(sum, channel))} | settlement pool at ({PCX},{PCY}) | NE reservoir at ({int(NE_CX)},{int(NE_CY)}) | skipped: {_skipped}")
print(collections.Counter(e["Template"][:11] if e["Template"].startswith("RuinColumn")
                          else e["Template"] for e in entities).most_common())
