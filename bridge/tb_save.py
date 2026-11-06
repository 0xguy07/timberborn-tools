"""Load and index a Timberborn .timber save.

A .timber file is a zip holding world.json (the whole simulation), plus
save_metadata.json, version.txt and a thumbnail.

Verified against game version 1.1.2.4. Grid layouts were confirmed empirically
against entity coordinates in a real save:
    terrain voxel i = z*X*Y + y*X + x        (values 0/1, solid)
    water column  i = level*X*Y + y*X + x    ("0" or "depth:contam:?:floorZ:prev")
"""

import json
import os
import zipfile
from collections import defaultdict

from tb_specs import (
    GENERATOR_KEYWORDS, HAULING_TEMPLATES, HOUSING_CAPACITY, SHAFT_KEYWORDS,
    STORAGE_TEMPLATES,
)


def saves_root():
    env = os.environ.get("TIMBERBORN_DIR")
    if env:
        return os.path.expanduser(env)
    for c in ("~/Documents/Timberborn", "~/Library/Application Support/Timberborn"):
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~/Documents/Timberborn")


def list_saves(settlement=None):
    root = os.path.join(saves_root(), "Saves")
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or (settlement and settlement.lower() not in name.lower()):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".timber"):
                continue
            p = os.path.join(d, f)
            st = os.stat(p)
            out.append({
                "settlement": name,
                "save": f[: -len(".timber")],
                "path": p,
                "autosave": ".autosave" in f,
                "mtime": st.st_mtime,
                "bytes": st.st_size,
            })
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def resolve(ref=None, settlement=None):
    """Resolve a save reference to a path. None -> newest save."""
    if ref and os.path.isfile(os.path.expanduser(ref)):
        return os.path.expanduser(ref)
    rows = list_saves(settlement)
    if not rows:
        raise FileNotFoundError("no .timber saves found under %s" % saves_root())
    if ref:
        low = ref.lower()
        hit = [r for r in rows if low in r["save"].lower() or low in r["path"].lower()]
        if not hit:
            raise FileNotFoundError("no save matching %r" % ref)
        return hit[0]["path"]
    return rows[0]["path"]


_CACHE = {}


def load(ref=None, settlement=None):
    path = resolve(ref, settlement)
    key = (path, os.stat(path).st_mtime)
    hit = _CACHE.get(key)
    if hit is None:
        _CACHE.clear()
        hit = _CACHE[key] = Save(path)
    return hit


class Save:
    def __init__(self, path):
        self.path = path
        self.settlement = os.path.basename(os.path.dirname(path))
        self.name = os.path.basename(path)[: -len(".timber")]
        with zipfile.ZipFile(path) as z:
            self.world = json.loads(z.read("world.json"))
            try:
                self.metadata = json.loads(z.read("save_metadata.json"))
            except KeyError:
                self.metadata = {}
            try:
                self.version = z.read("version.txt").decode().strip()
            except KeyError:
                self.version = self.world.get("GameVersion", "?")
        self.singletons = self.world["Singletons"]
        self.entities = self.world["Entities"]
        self._index()

    # ---------- indexing ----------

    def _index(self):
        self.by_id = {}
        self.by_template = defaultdict(list)
        self.by_component = defaultdict(list)
        for e in self.entities:
            self.by_id[e["Id"]] = e
            self.by_template[e.get("Template", "?")].append(e)
            for c in e["Components"]:
                self.by_component[c].append(e)

        self.districts = [e for e in self.by_component["DistrictPopulationBalance"]]
        self.district_names = {
            d["Id"]: d["Components"].get("NamedEntity", {}).get("EntityName", d["Id"][:8])
            for d in self.districts
        }

        self.citizens = [e for e in self.by_component["Citizen"]
                         if e["Components"].get("Character", {}).get("Alive", True)]

        # empirical housing capacity
        occ = defaultdict(int)
        for c in self.citizens:
            h = c["Components"].get("Dweller", {}).get("Home")
            if h:
                occ[h] += 1
        emp = defaultdict(int)
        for hid, n in occ.items():
            t = self.template(hid)
            emp[t] = max(emp[t], n)
        self._home_occupancy = occ
        self.housing_capacity = {
            t: max(n, HOUSING_CAPACITY.get(t, 0)) for t, n in emp.items()
        }

        self.workers_at = defaultdict(list)
        for c in self.citizens:
            w = c["Components"].get("Worker", {}).get("Workplace")
            if w:
                self.workers_at[w].append(c)

        self._district_of = {}

    # ---------- helpers ----------

    def template(self, eid):
        e = self.by_id.get(eid)
        return e.get("Template", "?") if e else "?"

    @staticmethod
    def coords(e):
        b = e["Components"].get("BlockObject", {}).get("Coordinates")
        if b:
            return (b.get("X", 0), b.get("Y", 0), b.get("Z", 0))
        p = e["Components"].get("Character", {}).get("Position")
        if p:  # note: character positions are (X, height, Z) in world space
            return (int(p.get("X", 0)), int(p.get("Z", 0)), int(p.get("Y", 0)))
        return None

    @staticmethod
    def finished(e):
        return "ConstructionSite" not in e["Components"]

    def buildings(self, finished_only=True):
        for e in self.entities:
            c = e["Components"]
            if "BlockObject" not in c:
                continue
            if "Growable" in c or "LivingNaturalResource" in c or "Yielder:Ruin" in c:
                continue
            if finished_only and not self.finished(e):
                continue
            yield e

    def is_kind(self, e, keywords):
        t = e.get("Template", "")
        return any(k in t for k in keywords)

    def storage(self, e):
        """Total goods in every inventory of an entity except its build site."""
        out = defaultdict(int)
        for k, v in e["Components"].items():
            if not k.startswith("Inventory:") or k == "Inventory:ConstructionSite":
                continue
            for g in v.get("Storage", {}).get("Goods", []):
                out[g["Good"]] += g["Amount"]
        return dict(out)

    # ---------- districts ----------

    def district_of(self, e):
        """District id for an entity.

        Exact when the building has assigned workers or dwellers (they carry
        Citizen.AssignedDistrict). Otherwise falls back to the nearest district
        center by XY distance, which is an approximation -- the game decides by
        path connectivity, which the save does not store.
        """
        eid = e["Id"]
        if eid in self._district_of:
            return self._district_of[eid]
        c = e["Components"]
        if "Citizen" in c:
            d = c["Citizen"].get("AssignedDistrict")
            self._district_of[eid] = d
            return d
        if "DistrictPopulationBalance" in c:
            self._district_of[eid] = eid
            return eid
        votes = defaultdict(int)
        for w in self.workers_at.get(eid, []):
            votes[w["Components"]["Citizen"].get("AssignedDistrict")] += 1
        for cz in self.citizens:
            if cz["Components"].get("Dweller", {}).get("Home") == eid:
                votes[cz["Components"]["Citizen"].get("AssignedDistrict")] += 1
        if votes:
            d = max(votes.items(), key=lambda kv: kv[1])[0]
        else:
            d = self.nearest_district(e)
        self._district_of[eid] = d
        return d

    def nearest_district(self, e):
        xy = self.coords(e)
        if not xy or not self.districts:
            return self.districts[0]["Id"] if self.districts else None
        best, bd = None, 1e18
        for d in self.districts:
            dc = self.coords(d)
            dist = abs(dc[0] - xy[0]) + abs(dc[1] - xy[1])
            if dist < bd:
                best, bd = d["Id"], dist
        return best

    def district_id(self, ref):
        """Accept a district name, partial name, or id."""
        if not ref:
            return None
        if ref in self.district_names:
            return ref
        low = ref.lower()
        for did, name in self.district_names.items():
            if low == name.lower() or low in name.lower():
                return did
        raise KeyError("no district matching %r (have: %s)"
                       % (ref, ", ".join(self.district_names.values())))

    # ---------- maps ----------

    @property
    def size(self):
        s = self.singletons["MapSize"]["Size"]
        return s["X"], s["Y"]

    def terrain(self):
        if not hasattr(self, "_terrain"):
            self._terrain = self.singletons["TerrainMap"]["Voxels"]["Array"].split(" ")
        return self._terrain

    def water_columns(self):
        """Yield (x, y, level, depth, contamination, floor_z) for wet columns."""
        X, Y = self.size
        raw = self.singletons["WaterMapNew"]["WaterColumns"]["Array"].split(" ")
        per = X * Y
        for i, v in enumerate(raw):
            if v == "0":
                continue
            f = v.split(":")
            level, rem = divmod(i, per)
            y, x = divmod(rem, X)
            yield (x, y, level, float(f[0]), float(f[1]), int(float(f[3])))

    def moisture(self):
        X, Y = self.size
        raw = self.singletons["SoilMoistureSimulator"]["MoistureLevels"]["Array"].split(" ")
        return X, Y, raw
