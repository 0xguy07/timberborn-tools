"""Report builders. Each returns markdown-ish text meant to be read by a model."""

from collections import Counter, defaultdict

import tb_specs as spec


def _pct(a, b):
    return "n/a" if not b else "%d%%" % round(100.0 * a / b)


def _table(rows, headers):
    if not rows:
        return "_(none)_"
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    out = ["| " + " | ".join(h.ljust(w[i]) for i, h in enumerate(headers)) + " |",
           "|" + "|".join("-" * (x + 2) for x in w) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r[i].ljust(w[i]) for i in range(len(headers))) + " |")
    return "\n".join(out)


def _series(save, district=None):
    """(good -> per-day samples) for the settlement or one district."""
    if district:
        d = save.by_id[district]
        reg = d["Components"].get("DistrictGoodSamplingRegistry", {})
        hist = reg.get("GoodSamplingRegistry", {}).get("GoodSampleHistory", [])
    else:
        reg = save.singletons.get("GlobalGoodSamplingRegistry", {})
        hist = reg.get("GoodSamplingRegistry", {}).get("GoodSampleHistory", [])
    return {h["Good"]: h for h in hist}


def _rate(h, key, days):
    v = h.get(key) or []
    v = v[-days:]
    return sum(v) / float(len(v)) if v else 0.0


def _weather(save):
    s = save.singletons
    haz = s.get("HazardousWeatherService", {})
    cyc = s.get("GameCycleService", {})
    temp = s.get("TemperateWeatherDurationService", {})
    return {
        "cycle": cyc.get("Cycle"),
        "day": cyc.get("CycleDay"),
        "total_days": s.get("DayNightCycle", {}).get("DayNumber"),
        "is_drought": haz.get("IsDrought", False),
        "hazard_days": haz.get("HazardousWeatherDuration"),
        "temperate_days": temp.get("TemperateWeatherDuration"),
    }


# --------------------------------------------------------------------------


def overview(save):
    s = save.singletons
    w = _weather(save)
    adults = [c for c in save.citizens if c["Template"].startswith("BeaverAdult")]
    kids = [c for c in save.citizens if "Child" in c["Template"]]
    bots = [c for c in save.citizens if "Bot" in c["Template"]]
    hist = s.get("HazardousWeatherHistory", {}).get("HistoryData", [])
    droughts = [h["Duration"] for h in hist if h["HazardousWeatherId"] == "DroughtWeather"]
    badtides = [h["Duration"] for h in hist if h["HazardousWeatherId"] == "BadtideWeather"]

    lines = [
        "# %s / %s" % (save.settlement, save.name),
        "game %s | faction %s | map %dx%d" % (
            save.version, s.get("FactionService", {}).get("Id", "?"), *save.size),
        "cycle %s day %s (day %s overall) | %s | %s" % (
            w["cycle"], w["day"], w["total_days"],
            "DROUGHT, %s day cycle" % w["hazard_days"] if w["is_drought"]
            else "temperate, %s day season" % w["temperate_days"],
            "science %s" % s.get("ScienceService", {}).get("SciencePoints"),
        ),
        "",
        "**Population** %d adults, %d children, %d bots (%d total)"
        % (len(adults), len(kids), len(bots), len(save.citizens)),
        "**Wellbeing highscore** %s" % s.get("WellbeingHighscore", {}).get(
            "AverageWellbeingHighscore"),
        "",
        "## Districts",
    ]
    rows = []
    for d in save.districts:
        did = d["Id"]
        cz = [c for c in save.citizens if c["Components"]["Citizen"].get("AssignedDistrict") == did]
        bal = d["Components"].get("DistrictPopulationBalance", {})
        rows.append([
            save.district_names[did],
            "%d,%d" % tuple(save.coords(d)[:2]),
            len(cz),
            sum(1 for c in cz if "Bot" in c["Template"]),
            "+%s/-%s" % (bal.get("Births", 0), bal.get("Deaths", 0)),
        ])
    lines.append(_table(rows, ["district", "at", "citizens", "bots", "born/died this cycle"]))

    lines += ["", "## Weather record",
              "droughts seen: %d, recent durations %s (max %s)"
              % (len(droughts), droughts[-8:], max(droughts) if droughts else 0),
              "badtides seen: %d, recent durations %s (max %s)"
              % (len(badtides), badtides[-8:], max(badtides) if badtides else 0)]

    stats = s.get("IncrementalStatisticCollector", {}).get("SettlementStatistics", [])
    if stats:
        lines += ["", "## Lifetime stats",
                  ", ".join("%s %s" % (x["Id"], x["Value"]) for x in stats)]

    unfinished = [e for e in save.entities if "ConstructionSite" in e["Components"]]
    lines += ["", "%d buildings under construction (see construction_report)" % len(unfinished)]
    return "\n".join(lines)


def districts(save, district=None):
    targets = [save.district_id(district)] if district else [d["Id"] for d in save.districts]
    out = []
    for did in targets:
        d = save.by_id[did]
        name = save.district_names[did]
        cz = [c for c in save.citizens
              if c["Components"]["Citizen"].get("AssignedDistrict") == did]
        adults = [c for c in cz if c["Template"].startswith("BeaverAdult")]
        kids = [c for c in cz if "Child" in c["Template"]]
        bots = [c for c in cz if "Bot" in c["Template"]]

        # housing
        homes = defaultdict(lambda: [0, 0])  # template -> [capacity, occupied]
        seen = set()
        for c in cz:
            h = c["Components"].get("Dweller", {}).get("Home")
            if h:
                seen.add(h)
        for hid in seen:
            t = save.template(hid)
            homes[t][1] += save._home_occupancy.get(hid, 0)
        for t in list(homes):
            n = sum(1 for hid in seen if save.template(hid) == t)
            homes[t][0] = n * save.housing_capacity.get(t, 0)
        cap = sum(v[0] for v in homes.values())
        housed = sum(v[1] for v in homes.values())
        homeless = sum(1 for c in cz
                       if "Dweller" in c["Components"]
                       and not c["Components"]["Dweller"].get("Home"))

        # jobs
        open_jobs, filled, rows = 0, 0, []
        for e in save.buildings():
            c = e["Components"]
            if "Workplace" not in c or save.district_of(e) != did:
                continue
            want = c["Workplace"].get("DesiredWorkers", 0)
            have = len(save.workers_at.get(e["Id"], []))
            filled += have
            open_jobs += max(0, want - have)
            if want > have:
                rows.append([e["Template"].split(".")[0], "%d,%d,%d" % save.coords(e),
                             want, have, c.get("WorkplacePriority", {}).get("Priority", "Normal"),
                             c.get("WorkplaceWorkerType", {}).get("WorkerType", "-")])
        idle = [c for c in adults + bots if not c["Components"].get("Worker", {}).get("Workplace")]

        # needs
        agg = defaultdict(list)
        for c in adults:
            for n in c["Components"].get("NeedManager", {}).get("Needs", []):
                agg[n["Name"]].append(n["Points"])
        need_rows = []
        for n, vals in sorted(agg.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            avg = sum(vals) / len(vals)
            low = sum(1 for v in vals if v < 0.25)
            need_rows.append([n, "%.2f" % avg, len(vals),
                              "%d (%s)" % (low, _pct(low, len(vals))),
                              "survival" if n in spec.SURVIVAL_NEEDS else "wellbeing"])
        buffs = [sum(1 for n in c["Components"].get("NeedManager", {}).get("Needs", [])
                     if n["Name"] not in spec.SURVIVAL_NEEDS and n["Points"] > 0.05)
                 for c in adults]

        bal = d["Components"].get("DistrictGoodsBalance", {})
        prod = {g["Good"]: g["Amount"] for g in bal.get("ProductionRegistry", {}).get("Goods", [])}
        cons = {g["Good"]: g["Amount"] for g in bal.get("ConsumptionRegistry", {}).get("Goods", [])}
        goods = sorted(set(prod) | set(cons), key=lambda g: -(cons.get(g, 0)))
        flow = [[g, prod.get(g, 0), cons.get(g, 0), prod.get(g, 0) - cons.get(g, 0)]
                for g in goods]

        out.append("\n".join([
            "# District: %s" % name,
            "center at %d,%d,%d" % save.coords(d),
            "",
            "**People** %d adults, %d children, %d bots. Idle (no workplace): %d."
            % (len(adults), len(kids), len(bots), len(idle)),
            "**Housing** %d beds across %d homes, %d occupied (%s). Homeless: %d."
            % (cap, len(seen), housed, _pct(housed, cap), homeless),
            "  " + ", ".join("%s x%d" % (t.split(".")[0], sum(1 for h in seen if save.template(h) == t))
                             for t in sorted(homes)),
            "**Jobs** %d filled, %d open slots." % (filled, open_jobs),
            "**Wellbeing needs met per adult** %.1f (avg)"
            % (sum(buffs) / float(len(buffs)) if buffs else 0),
            "",
            "## Unfilled workplaces",
            _table(rows[:40], ["building", "at", "want", "have", "priority", "type"]),
            "",
            "## Needs (points 0-1, 1 = satisfied; negative needs are active penalties)",
            _table(need_rows, ["need", "avg", "adults with it", "under 0.25", "kind"]),
            "",
            "## Goods this cycle (district registry)",
            _table(flow[:30], ["good", "produced", "consumed", "net"]),
        ]))
    return "\n\n---\n\n".join(out)


def food_water(save, district=None, days=10):
    ids = [save.district_id(district)] if district else [None] + [d["Id"] for d in save.districts]
    out = []
    w = _weather(save)
    hist = save.singletons.get("HazardousWeatherHistory", {}).get("HistoryData", [])
    droughts = [h["Duration"] for h in hist if h["HazardousWeatherId"] == "DroughtWeather"]
    worst = max(droughts[-10:]) if droughts else 0

    for did in ids:
        label = save.district_names[did] if did else "SETTLEMENT (all districts)"
        ser = _series(save, did)
        food_rows, water_rows = [], []
        food_stock = food_cons = 0
        for good, h in ser.items():
            stock = (h.get("Stock") or [0])[-1]
            cap = (h.get("Capacity") or [0])[-1]
            p = _rate(h, "Production", days)
            c = _rate(h, "Consumption", days)
            if stock == 0 and p == 0 and c == 0:
                continue
            row = [good, stock, cap, _pct(stock, cap), "%.0f" % p, "%.0f" % c,
                   "%+.0f" % (p - c),
                   "%.1f" % (stock / c) if c > 0.5 else "-"]
            if good in spec.WATER_GOODS:
                water_rows.append(row)
            elif good in spec.EDIBLE:
                food_rows.append(row)
                if good not in spec.NON_FOOD_CROPS:
                    food_stock += stock
                    food_cons += c
        head = ["good", "stock", "cap", "full", "prod/day", "cons/day", "net", "days left"]
        food_rows.sort(key=lambda r: -r[1])
        water = ser.get("Water", {})
        wstock = (water.get("Stock") or [0])[-1]
        wcons = _rate(water, "Consumption", days)
        wprod = _rate(water, "Production", days)

        block = [
            "# Food & water: %s" % label,
            "rates are the mean of the last %d days, from the in-game sampling registry" % days,
            "",
            "**Water** stock %d, using %.0f/day, making %.0f/day -> %s days of buffer"
            % (wstock, wcons, wprod, "%.1f" % (wstock / wcons) if wcons else "inf"),
            "**Food (edible goods)** stock %d, eating %.0f/day -> %s days"
            % (food_stock, food_cons, "%.1f" % (food_stock / food_cons) if food_cons else "inf"),
            "",
            "## Water",
            _table(water_rows, head),
            "",
            "## Food",
            _table(food_rows[:25], head),
        ]
        if did is None:
            block += ["", "## Drought exposure",
                      "now: %s. Recent drought lengths %s (worst of last 10: %d days)."
                      % ("DROUGHT day of %s" % w["hazard_days"] if w["is_drought"]
                         else "temperate", droughts[-10:], worst),
                      "At %.0f water/day, surviving a %d-day drought with no pumping needs "
                      "~%d water in store; you hold %d (%s)."
                      % (wcons, worst, wcons * worst, wstock,
                         "OK" if wstock >= wcons * worst else "SHORT by %d" % (wcons * worst - wstock))]
        out.append("\n".join(block))

    out.append(reservoir(save))
    return "\n\n---\n\n".join(out)


def reservoir(save):
    X, Y = save.size
    total = contaminated = 0.0
    wet = 0
    by_floor = defaultdict(float)
    deep = []
    for x, y, level, depth, contam, floor in save.water_columns():
        total += depth
        contaminated += depth * min(max(contam, 0.0), 1.0)
        wet += 1
        by_floor[floor] += depth
        if depth > 2.0:
            deep.append((depth, x, y, floor))
    deep.sort(reverse=True)
    sources = []
    for e in save.by_component["WaterSource"]:
        c = e["Components"]["WaterSource"]
        cur, spec_ = c.get("CurrentStrength", 0), c.get("SpecifiedStrength", 0)
        sources.append([e["Template"], "%d,%d,%d" % save.coords(e),
                        "%.2f" % cur, "%.2f" % spec_,
                        "not flowing" if cur <= 0 else
                        ("throttled" if cur < spec_ - 1e-6 else "full")])
    gates = []
    for e in save.by_component["Floodgate"]:
        f = e["Components"]["Floodgate"]
        gates.append([e["Template"].split(".")[0], "%d,%d,%d" % save.coords(e),
                      "%.2f" % f.get("Height", 0), f.get("AutomationHeight"),
                      "yes" if f.get("IsSynchronized") else "no",
                      "BUILDING" if not save.finished(e) else ""])
    dams = sum(1 for e in save.buildings() if "Dam" in e["Template"])
    levees = sum(1 for e in save.buildings() if "Levee" in e["Template"])
    return "\n".join([
        "# Water on the map",
        "stored volume %.0f blocks across %d wet columns; %.0f blocks (%s) contaminated"
        % (total, wet, contaminated, _pct(contaminated, total or 1)),
        "dams %d, levees %d, floodgates %d" % (dams, levees, len(gates)),
        "",
        "## Volume by floor height",
        _table(sorted(([z, "%.0f" % v] for z, v in by_floor.items()), key=lambda r: r[0]),
               ["floor z", "volume"]),
        "",
        "## Deepest columns (depth, x, y, floor)",
        _table([["%.1f" % d, x, y, f] for d, x, y, f in deep[:15]],
               ["depth", "x", "y", "floor z"]),
        "",
        "## Water sources",
        _table(sources, ["template", "at", "current", "specified", "flow"]),
        "",
        "## Floodgates",
        _table(gates[:30], ["gate", "at", "height", "automation", "synced", "note"]),
    ])


def power(save):
    gens = defaultdict(lambda: [0, 0])   # template -> [count, nominal hp]
    per_district = defaultdict(int)
    for e in save.buildings():
        if save.is_kind(e, spec.GENERATOR_KEYWORDS):
            t = e["Template"]
            hp = spec.GENERATOR_HP.get(t, 0)
            gens[t][0] += 1
            gens[t][1] += hp
            per_district[save.district_of(e)] += hp
    shafts = Counter(e["Template"] for e in save.buildings()
                     if save.is_kind(e, spec.SHAFT_KEYWORDS))
    batteries = Counter(e["Template"] for e in save.buildings() if "Battery" in e["Template"])

    starved = []
    for e in save.buildings():
        c = e["Components"]
        counter = c.get("WorkshopProductivityCounter")
        if not counter:
            continue
        hours = counter.get("DailyProductivity", {}).get("HourlyProductivities", [])
        mx = sum(h["MaxWorkPotential"] for h in hours if h.get("WasWorkingHour"))
        ac = sum(h["ActualWorkPerformed"] for h in hours if h.get("WasWorkingHour"))
        if mx <= 0:
            continue
        ratio = ac / float(mx)
        want = c.get("Workplace", {}).get("DesiredWorkers", 0)
        have = len(save.workers_at.get(e["Id"], []))
        starved.append((ratio, e, want, have))
    starved.sort(key=lambda r: r[0])

    rows = [[t, v[0], v[1] or "unknown", save.district_names.get(save.district_of(
        save.by_template[t][0]), "?")] for t, v in sorted(gens.items())]
    worst = [["%.0f%%" % (r * 100), e["Template"].split(".")[0], "%d,%d,%d" % save.coords(e),
              "%d/%d" % (have, want),
              save.district_names.get(save.district_of(e), "?")]
             for r, e, want, have in starved[:25]]
    return "\n".join([
        "# Power",
        "_Nominal hp is the wiki rating at full output, not a measurement. The save "
        "does not store the power network, so grid-by-grid balance is not available; "
        "the productivity table below is the real evidence of starved buildings._",
        "",
        "## Generators",
        _table(rows, ["template", "count", "nominal hp", "district"]),
        "total nominal capacity: %d hp" % sum(v[1] for v in gens.values()),
        "",
        "## Transmission & storage",
        "shafts: %s" % (", ".join("%s x%d" % (k.split(".")[0], v) for k, v in shafts.items()) or "none"),
        "batteries: %s" % (", ".join("%s x%d" % (k.split(".")[0], v) for k, v in batteries.items()) or "none"),
        "",
        "## Lowest productivity yesterday (power, inputs or staffing)",
        _table(worst, ["done/possible", "building", "at", "staff", "district"]),
    ])


def logistics(save, district=None):
    did = save.district_id(district) if district else None
    posts, stores, unallocated = [], [], 0
    store_coords = []
    for e in save.buildings():
        d = save.district_of(e)
        if did and d != did:
            continue
        t = e["Template"]
        if save.is_kind(e, spec.HAULING_TEMPLATES):
            want = e["Components"].get("Workplace", {}).get("DesiredWorkers", 0)
            have = len(save.workers_at.get(e["Id"], []))
            inv = save.storage(e)
            posts.append([t.split(".")[0], "%d,%d,%d" % save.coords(e),
                          "%d/%d" % (have, want), save.district_names.get(d, "?"),
                          ", ".join("%s %d" % (k, v) for k, v in sorted(
                              inv.items(), key=lambda kv: -kv[1])[:5]) or "empty"])
        if save.is_kind(e, spec.STORAGE_TEMPLATES):
            inv = save.storage(e)
            allowed = e["Components"].get("SingleGoodAllower", {}).get("AllowedGood")
            if not allowed:
                unallocated += 1
            stores.append([t.split(".")[0], "%d,%d,%d" % save.coords(e),
                           allowed or "UNSET", sum(inv.values()),
                           save.district_names.get(d, "?")])
            store_coords.append((save.coords(e), d))

    far = []
    for e in save.buildings():
        c = e["Components"]
        if "Workplace" not in c or "DistrictCenter" in e["Template"]:
            continue
        d = save.district_of(e)
        if did and d != did:
            continue
        xy = save.coords(e)
        best = min((abs(sc[0] - xy[0]) + abs(sc[1] - xy[1]) + abs(sc[2] - xy[2]) * 2
                    for sc, sd in store_coords if sd == d), default=None)
        if best is not None:
            far.append((best, e, d))
    far.sort(key=lambda r: -r[0])

    dist_rows = []
    for dc in save.districts:
        if did and dc["Id"] != did:
            continue
        settings = dc["Components"].get("DistrictDistributionSetting", {}).get(
            "GoodDistributionSettings", [])
        forced = [s["GoodId"] for s in settings if s.get("ImportOption") == "Forced"]
        off = [s["GoodId"] for s in settings if s.get("ImportOption") == "Off"]
        exports = [(s["GoodId"], s["ExportThreshold"]) for s in settings
                   if s.get("ExportThreshold", 0) > 0]
        dist_rows.append([save.district_names[dc["Id"]],
                          ", ".join(forced) or "-",
                          ", ".join(off) or "-",
                          ", ".join("%s>%g" % x for x in exports) or "-"])

    agg = defaultdict(lambda: [0, 0])          # (district, good) -> [buildings, amount]
    empty = 0
    for r in stores:
        a = agg[(r[4], r[2])]
        a[0] += 1
        a[1] += r[3]
        if r[3] == 0:
            empty += 1
    agg_rows = [[d, g, v[0], v[1]] for (d, g), v in
                sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1][1]))]
    return "\n".join([
        "# Logistics",
        "_Distances are Manhattan on the grid with a x2 weight on height, not walked "
        "path length -- treat them as a shortlist, not a measurement._",
        "",
        "## Hauling posts & district crossings",
        _table(posts, ["building", "at", "staff", "district", "holding"]),
        "",
        "## Storage: %d buildings, %d unassigned, %d sitting empty"
        % (len(stores), unallocated, empty),
        _table(agg_rows, ["district", "good", "buildings", "held"]),
        "",
        "empty or unassigned storage:",
        _table([r for r in stores if r[3] == 0 or r[2] == "UNSET"][:30],
               ["building", "at", "holds", "amount", "district"]),
        "",
        "## Workplaces furthest from any storage in their district",
        _table([[d, e["Template"].split(".")[0], "%d,%d,%d" % save.coords(e),
                 save.district_names.get(dd, "?")] for d, e, dd in far[:20]],
               ["distance", "building", "at", "district"]),
        "",
        "## Cross-district goods policy",
        _table(dist_rows, ["district", "forced import", "blocked", "export threshold"]),
    ])


def workplaces(save, district=None, limit=60):
    did = save.district_id(district) if district else None
    rows = []
    for e in save.buildings():
        c = e["Components"]
        if "Workplace" not in c:
            continue
        d = save.district_of(e)
        if did and d != did:
            continue
        want = c["Workplace"].get("DesiredWorkers", 0)
        have = len(save.workers_at.get(e["Id"], []))
        hours = c.get("WorkshopProductivityCounter", {}).get(
            "DailyProductivity", {}).get("HourlyProductivities", [])
        mx = sum(h["MaxWorkPotential"] for h in hours if h.get("WasWorkingHour"))
        ac = sum(h["ActualWorkPerformed"] for h in hours if h.get("WasWorkingHour"))
        inv = save.storage(e)
        rows.append([
            "%d%%" % round(100.0 * ac / mx) if mx else "-",
            e["Template"].split(".")[0], "%d,%d,%d" % save.coords(e),
            "%d/%d" % (have, want),
            c.get("WorkplacePriority", {}).get("Priority", "Normal"),
            save.district_names.get(d, "?"),
            ", ".join("%s %d" % (k, v) for k, v in sorted(inv.items(), key=lambda kv: -kv[1])[:3]) or "-",
        ])
    rows.sort(key=lambda r: (r[0] == "-", int(r[0].rstrip("%")) if r[0] != "-" else 999))
    return "\n".join([
        "# Workplaces by productivity (yesterday)",
        "_'done' is work performed vs. work possible during working hours: low means "
        "missing workers, missing inputs, no power, or a full output inventory._",
        "",
        _table(rows[:limit], ["done", "building", "at", "staff", "priority", "district", "holding"]),
    ])


def construction(save):
    rows = []
    for e in save.entities:
        c = e["Components"]
        if "ConstructionSite" not in c:
            continue
        inv = {}
        for g in c.get("Inventory:ConstructionSite", {}).get("Storage", {}).get("Goods", []):
            inv[g["Good"]] = g["Amount"]
        rows.append([e["Template"].split(".")[0],
                     "%d,%d,%d" % (save.coords(e) or (0, 0, 0)),
                     "%.1f h" % c["ConstructionSite"].get("BuildTimeProgressInHours", 0),
                     ", ".join("%s %d" % kv for kv in sorted(inv.items())) or "nothing delivered",
                     save.district_names.get(save.district_of(e), "?")])
    counts = Counter(r[0] for r in rows)
    builders = [e for e in save.buildings() if "BuildersHut" in e["Template"]]
    staffed = sum(len(save.workers_at.get(b["Id"], [])) for b in builders)
    want = sum(b["Components"].get("Workplace", {}).get("DesiredWorkers", 0) for b in builders)
    return "\n".join([
        "# Under construction: %d sites" % len(rows),
        "builders' huts: %d, staffed %d/%d" % (len(builders), staffed, want),
        "by type: " + ", ".join("%s x%d" % kv for kv in counts.most_common(20)),
        "",
        _table(rows[:60], ["building", "at", "progress", "materials on site", "district"]),
    ])


def find_buildings(save, query, limit=60):
    q = query.lower()
    rows = []
    for e in save.buildings(finished_only=False):
        t = e["Template"]
        name = e["Components"].get("NamedEntity", {}).get("EntityName", "")
        if q not in t.lower() and q not in name.lower():
            continue
        c = e["Components"]
        want = c.get("Workplace", {}).get("DesiredWorkers", 0)
        have = len(save.workers_at.get(e["Id"], []))
        inv = save.storage(e)
        rows.append([t.split(".")[0], name or "-", "%d,%d,%d" % (save.coords(e) or (0, 0, 0)),
                     "%d/%d" % (have, want) if want else "-",
                     "" if save.finished(e) else "BUILDING",
                     ", ".join("%s %d" % kv for kv in sorted(inv.items(), key=lambda kv: -kv[1])[:4]) or "-",
                     save.district_names.get(save.district_of(e), "?")])
    return "\n".join([
        "# Buildings matching %r: %d" % (query, len(rows)),
        _table(rows[:limit], ["template", "name", "at", "staff", "state", "holding", "district"]),
    ])


def good_history(save, good, district=None, days=40):
    did = save.district_id(district) if district else None
    ser = _series(save, did)
    h = ser.get(good)
    if not h:
        return "No history for %r. Tracked goods: %s" % (good, ", ".join(sorted(ser)))
    n = min(days, len(h.get("Stock", [])))
    rows = []
    for i in range(-n, 0):
        rows.append([h["Cycle"][i], h["Day"][i], h["Stock"][i], h["Capacity"][i],
                     h["Production"][i], h["Consumption"][i],
                     h["Production"][i] - h["Consumption"][i]])
    return "\n".join([
        "# %s in %s, last %d days" % (good, save.district_names.get(did, "the settlement"), n),
        _table(rows, ["cycle", "day", "stock", "capacity", "produced", "consumed", "net"]),
    ])


def raw(save, path="", limit=4000):
    import json as _json
    node = {"Singletons": save.singletons,
            "Entities": "%d entities (use find_buildings)" % len(save.entities)}
    for part in [p for p in path.split(".") if p]:
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                return "no key %r at that level; keys: %s" % (part, list(node)[:80])
            node = node[part]
        else:
            return "cannot descend into %s" % type(node).__name__
    if isinstance(node, dict):
        out = {k: (v if len(_json.dumps(v)) < 400 else "<%d chars, descend with path>"
                   % len(_json.dumps(v))) for k, v in node.items()}
        return _json.dumps(out, indent=1)[:limit]
    return _json.dumps(node, indent=1)[:limit]
