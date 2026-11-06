# Timberborn — mechanics and build notes

Observations from instrumenting a real 600-day Folktails colony (Denniston,
cycle 31, ~660 beavers across two districts) on game version 1.1.2.4. Numbers
come from the save file and from live game memory, not from guides.

---

## Building geometry — read this before placing anything

Every building declares a `BlockObjectSpec` with a footprint `Size` and an
**entrance offset**. The entrance is the tile a beaver must stand on, and for
most buildings it sits *outside* the footprint.

| Building | Size (x,y,z) | Entrance offset | Flippable |
|---|---|---|---|
| Lodge | 2 × 2 × 1 | **(+1, −1, 0)** | yes |
| Mini Lodge | 1 × 2 × 1 | (0, −1, 0) | no |
| Triple Lodge | 3 × 2 × 2 | (+1, −1, +1) | no |
| Medium Warehouse | 3 × 2 × 1 | (+1, −1, 0) | no |
| Path | 1 × 1 × 1 | none | no |
| Platform | 1 × 1 × 1 | none | no |
| Double / Triple Platform | 1 × 1 × 2 / ×3 | none | no |
| Spiral Stairs | 1 × 1 × 2 | none | yes |

**The practical rule:** "next to a path" is not the requirement. One specific
tile has to be walkable. For an unrotated Lodge whose origin is `(x,y,z)`, the
doorstep is `(x+1, y−1, z)`.

Inverted, to put a Lodge's door onto an existing path tile `(px,py,pz)`, place
its origin at `(px−1, py+1, pz)`.

Getting this wrong produces buildings that construct normally, look fine, and
are never used — flagged only by a small red icon you have to notice yourself.

---

## Foundations and stacking — the actual rule

Read from the game's own enums, not the wiki (which does not document this):

```
BlockStackable    None | BlockObject | UnfinishedGround
MatterBelow       Ground | GroundOrStackable | Air | Any | Stackable
BlockOccupations  None | All | Floor | Bottom | Top | Corners | Path | Middle
```

Every building's `BlockObjectSpec.Blocks` carries a `BlockSpec` per block with
`MatterBelow` (what it needs underneath), `Stackable` (whether anything may be
built on its top face), `Occupations`, `OccupyAllBelow` and `Underground`.

**Anything whose block is `Stackable = BlockObject` is a foundation.** Platforms
are not special — they are simply cheap, 1x1, and stackable. A house, a
warehouse or a workshop with a stackable top face works exactly as well, and
building on existing rooftops is the correct way to densify a built-out core
rather than hunting for empty ground.

A building placed above needs `MatterBelow` of `GroundOrStackable`, `Stackable`
or `Any` — one requiring `Ground` will refuse to sit on a rooftop.

## Vertical building

- Platforms rest on solid ground, on other platforms, or on buildings that
  support stacking. **Deleting a support destroys everything above it.**
- Beavers cannot climb. Vertical access needs stairs or (Iron Teeth) tubeways.
- **Spiral Stairs are 1×1 per level and stack directly on each other** — the
  cheapest vertical access by footprint, and the key to dense housing.
- Rule of thumb: one stair column per 8–10 tiles of floor per level.
- Sensible vertical zoning: gathering at ground level, workshops in the middle
  (near power), housing and storage on top.
- **Build wide before tall.** Tall single-access towers create pathfinding
  bottlenecks that cost more than the space they save.

A platform deck with a stair column and lodges packed on top beats scattering
lodges across whatever flat gaps exist — which is the mistake worth avoiding.

---

## Districts, labour and housing

The three numbers that actually govern a district:

1. **Adults vs. filled jobs** — the idle pool
2. **Desired vs. assigned workers** — the unfilled demand
3. **Free beds** — the hard cap on everything else

Denniston at cycle 31 showed the classic failure: one district with 174 jobs,
all filled, and 62 adults with nothing to do; the neighbouring district 52
workers short with 13 buildings completely unstaffed. Textbook misallocation.

**The trap:** migrating the idle beavers straight over makes them homeless,
because both districts sat at 8 free beds. Homelessness costs wellbeing and
eventually lives. Housing is the binding constraint, always. The working loop:

```
place housing  →  ensure builders' huts are staffed and High priority
               →  migrate only as many adults as there are free beds
               →  repeat as lodges complete
```

Run that and the imbalance closes. In practice it moved ~52 beavers from idle
to employed and took the second district from 326/378 staffed to **378/378**.

**Builders are the hidden bottleneck.** Queued construction does nothing if the
builders' huts are unstaffed — and in a labour-short district they will be,
because they compete with everything else. Setting them to High priority is
what makes the rest of the plan execute.

Priority visibly works: a gear workshop sitting at `0/1` picked up a worker
right after a bump to High, while its identical neighbour at Normal stayed empty.

---

## Wellbeing is the biggest lever in the game

Source: the official wiki, which is the canonical reference — <https://timberborn.wiki.gg/>

Wellbeing is not a comfort stat. It multiplies output:

| Wellbeing score | Work speed | Life expectancy | Movement |
|---|---|---|---|
| 5–6 | +20% | — | +5% (from 2–4) |
| ~30 | mid-scale | mid-scale | mid-scale |
| 67–71 | **+260%** | **+120%** | +70% |

Growth speed for kits scales +5% → +70%. Score 15 unlocks Iron Teeth for a
Folktails player.

A colony sitting at single-digit wellbeing is leaving a multiple of its labour
on the table. Denniston's highscore was 14 with adults averaging 5–6 satisfied
needs — meaning most of its beavers work at a fraction of their possible rate.

### Wellbeing points per need

| Need | Satisfied | Unsatisfied |
|---|---|---|
| Hunger | +1 | **−10** |
| Thirst | +1 | **−10** |
| Shelter | +1 | −3 |
| Sleep | +1 | −1 |
| Wet fur | +1 | — |
| Contamination (ailment) | — | **−10** |
| Injury (ailment) | — | −2 |
| Chipped teeth / bee sting | — | −1 |
| Social life (campfire, terrace, contemplation spot) | +1 to +5 | — |
| Fun (lido, carousel, mud pit, exercise plaza…) | +1 to +5 | — |
| Aesthetics (shrub, lantern, statue, bell…) | +1 to +2 | — |
| **Awe — monuments** | **+3 to +10** | — |

**Monuments are the densest source of wellbeing in the game.** Denniston already
owns a Farmer Monument and a Brazier of Bonding, and 92–94% of its adults sat
below 0.25 satisfaction on both — the buildings exist but their effect is not
reaching the population. Fixing monument coverage is worth more than any number
of new workshops.

The asymmetry on Hunger and Thirst is worth internalising: satisfied is worth
+1, unsatisfied is **−10**. Food and water are not where you optimise for
wellbeing; they are where you avoid catastrophe. Everything above subsistence
comes from social, fun, aesthetics and awe.

## District boundaries and builder range

- A district extends from its District Center along **connected paths**, until it
  meets a District Crossing. Path networks of two districts may not touch.
- **Builders work up to 10 blocks from a path.** This is the rule that silently
  kills remote construction: a site further than 10 blocks from connected path
  is never built, with no warning — the queue simply never moves.
- Workers do not cross District Crossings on their own; moving them is a manual
  migration from the district center panel.
- District Crossings staff up to 10 haulers per side to move goods between
  districts.
- Since Update 6 paths may extend indefinitely; the colouring (green → red past
  ~70 blocks) is guidance about walking distance, not a hard limit.

## Power, corrected

Earlier numbers in this project were wrong — flat wiki ratings misread as
constants. The real figures:

| Generator | Output |
|---|---|
| Power Wheel (FT/IT) | 50 hp, scaling 35–85 with movement speed, 1 beaver |
| Large Power Wheel (IT) | 75 hp per beaver × 4, up to 510 hp |
| Water Wheel (FT) | **270 hp per m³/s of current** |
| Compact Water Wheel (IT) | 120 hp per m³/s |
| Large Water Wheel (IT) | 540 hp per m³/s |
| Wind Turbine (FT) | 150 hp peak, ~68 hp average |
| Large Wind Turbine (FT) | 300 hp peak, ~144 hp average, 1400 science |
| Steam Engine (IT) | 400 hp, burns logs |

Water wheels scale with **current**, not with being in water — a wheel in still
water produces nothing. Shortage slows powered buildings rather than stopping
them; a disconnected building stops entirely. Paused buildings, unstaffed
buildings and buildings outside working hours draw no power at all.

## Reading a colony quickly

The game samples per-day statistics per district and settlement-wide — stock,
capacity, production and consumption for all 40 goods, ~500 days of history.
That is the fastest honest read on a colony, far better than eyeballing panels.

Useful derived numbers:

- **Days of buffer** = stock ÷ mean daily consumption over the last ~10 days
- **Drought exposure** = daily water use × worst recent drought length, against
  stored water
- **Workplace productivity** = work performed ÷ work possible during working
  hours, per building, per hour. Low values mean missing workers, missing
  inputs, no power, or a full output inventory — it is the single best signal
  for "this building is sick" and needs no spec data

What that surfaced in Denniston: 61 days of water buffer against a worst-case
4-day drought (wildly over-provisioned, with 96 storage buildings allocated to
water), sunflower seeds down to 1.7 days in the south while the north sat on
1,900, and gear running net −3/cycle with four workshops idle.

---

## Weather and water

- Drought and badtide durations grow with cycle number; the recent history is a
  better planning input than any fixed number. Denniston's last ten droughts ran
  2–4 days.
- Water is stored per map column with a contamination fraction — total volume,
  contaminated share and depth by elevation are all computable from a save.
- Badwater sources can be map-scripted to activate after N cycles. Check for
  sources with `CurrentStrength` at 0 but a nonzero `SpecifiedStrength`; they
  are armed, not dead.

---

## Save file format

`.timber` is a zip containing `world.json`, `save_metadata.json`, `version.txt`
and a thumbnail. `world.json` holds `Singletons` (map, water, weather, science,
per-district sampling registries) and `Entities` (every object, as a component
bag).

Grid layouts, confirmed empirically against known entity coordinates:

```
terrain voxel   index = z*X*Y + y*X + x      value "0"/"1" (solid)
water column    index = level*X*Y + y*X + x  "depth:contamination:?:floorZ:prevDepth"
```

Buildings do **not** store their district — the game derives it from path
connectivity. You can recover it exactly for any staffed or inhabited building,
because citizens carry `Citizen.AssignedDistrict`; everything else needs a
nearest-centre approximation.

Housing capacity is not in the save either, but it is derivable: group dwellers
by home and take the maximum observed per template. That yields Lodge 3,
Mini Lodge 1, Triple Lodge 9 — which the wiki confirms.
