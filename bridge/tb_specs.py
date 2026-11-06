"""Curated Timberborn constants.

The game does not store building specs in the save file, so anything that needs
a spec lives here. Values marked NOMINAL are from the wiki and are ratings, not
measurements -- the reports say so wherever they use them.

Housing capacity is only a fallback: tb_save derives capacity empirically from
the save (max dwellers ever observed in a building of that template) and takes
whichever number is larger.
"""

HOUSING_CAPACITY = {
    "Lodge.Folktails": 3,
    "MiniLodge.Folktails": 1,
    "TripleLodge.Folktails": 9,
    "Shelter.IronTeeth": 3,
    "Bunk.IronTeeth": 6,
    "Barracks.IronTeeth": 12,
    "Tower.IronTeeth": 24,
}

# Typical output. Water wheels are rated per m3/s of CURRENT, so a wheel in
# still water yields nothing -- these are averages, never guarantees.
# Source: https://timberborn.wiki.gg/wiki/Power
GENERATOR_HP = {
    "WaterWheel.Folktails": 270,          # per m3/s of current
    "CompactWaterWheel.IronTeeth": 120,   # per m3/s
    "LargeWaterWheel.IronTeeth": 540,     # per m3/s
    "WindTurbine.Folktails": 68,          # 150 peak
    "LargeWindTurbine.Folktails": 144,    # 300 peak
    "PowerWheel.Folktails": 50,           # 35-85 with movement speed
    "PowerWheel.IronTeeth": 50,
    "LargePowerWheel.IronTeeth": 300,     # 75 per beaver x4, up to 510
    "Engine.IronTeeth": 400,              # burns logs
}

POWER_STORAGE = {
    "GravityBattery.Folktails": 1500,
    "LargeGravityBattery.Folktails": 6000,
    "GravityBattery.IronTeeth": 1500,
    "LargeGravityBattery.IronTeeth": 6000,
}

EDIBLE = {
    "Berries", "Carrot", "Potato", "Chestnut", "Spadderdock", "Wheat",
    "SunflowerSeeds", "GrilledPotato", "GrilledChestnut", "GrilledSpadderdock",
    "Bread", "CattailCracker", "MaplePastry", "CattailRoot", "Dandelion",
    "Kohlrabi", "Egg", "Canola",
}

# Goods that only matter as inputs, listed so reports can separate them out.
NON_FOOD_CROPS = {"Wheat", "CattailRoot", "Canola", "Dandelion"}

WATER_GOODS = {"Water", "Badwater"}

STORAGE_TEMPLATES = (
    "Warehouse", "Tank", "UndergroundPile", "Stockpile", "Silo", "Pile",
)

HAULING_TEMPLATES = ("HaulingPost", "DistrictCrossing", "DistrictGate")

GENERATOR_KEYWORDS = ("WaterWheel", "WindTurbine", "PowerWheel", "Engine")

SHAFT_KEYWORDS = ("PowerShaft", "VerticalPowerShaft", "PowerTransmitter")

NEED_LABELS = {
    "Hunger": "food",
    "Thirst": "water",
    "Sleep": "sleep",
    "Shelter": "shelter",
}

# Needs whose points are wellbeing buffs rather than survival meters.
SURVIVAL_NEEDS = {"Hunger", "Thirst", "Sleep", "Shelter", "Biofuel"}
