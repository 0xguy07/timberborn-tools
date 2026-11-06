using System;
using System.Collections.Generic;
using System.Linq;
using Timberborn.BaseComponentSystem;
using Timberborn.BlockSystem;
using Timberborn.BlueprintSystem;
using Timberborn.BuilderPrioritySystem;
using Timberborn.BuildingsReachability;
using Timberborn.CameraSystem;
using Timberborn.ConstructionSites;
using Timberborn.Coordinates;
using Timberborn.DwellingSystem;
using Timberborn.EntitySystem;
using Timberborn.GameCycleSystem;
using Timberborn.GameDistricts;
using Timberborn.GameDistrictsMigration;
using Timberborn.GameSaveRepositorySystem;
using Timberborn.GameSaveRuntimeSystem;
using Timberborn.HazardousWeatherSystem;
using Timberborn.InventorySystem;
using Timberborn.Navigation;
using Timberborn.PrioritySystem;
using Timberborn.SettlementNameSystem;
using Timberborn.TemplateCollectionSystem;
using Timberborn.TemplateSystem;
using Timberborn.TimeSystem;
using Timberborn.WeatherSystem;
using Timberborn.WorkSystem;
using UnityEngine;

namespace BeaverBridge
{
    /// <summary>
    /// Every endpoint. Runs on the main thread only; BridgeServer guarantees that.
    /// Reads come straight from the game's own registries. Writes go through the
    /// same services the UI uses, so the game validates them.
    /// </summary>
    public class GameApi
    {
        readonly DistrictCenterRegistry _districts;
        readonly GameCycleService _cycle;
        readonly IDayNightCycle _dayNight;
        readonly WeatherService _weather;
        readonly HazardousWeatherService _hazard;
        readonly SpeedManager _speed;
        readonly TemplateCollectionService _templates;
        readonly ConstructionFactory _construction;
        readonly EntityService _entities;
        readonly EntityRegistry _entityRegistry;
        readonly IBlockService _blocks;
        readonly CameraService _camera;
        readonly GameSaver _saver;
        readonly SettlementReferenceService _settlement;
        readonly MigrationService _migration;

        public GameApi(DistrictCenterRegistry districts, GameCycleService cycle, IDayNightCycle dayNight,
                       WeatherService weather, HazardousWeatherService hazard, SpeedManager speed,
                       TemplateCollectionService templates, ConstructionFactory construction,
                       EntityService entities, EntityRegistry entityRegistry, IBlockService blocks,
                       CameraService camera, GameSaver saver, SettlementReferenceService settlement,
                       MigrationService migration)
        {
            _districts = districts; _cycle = cycle; _dayNight = dayNight; _weather = weather; _hazard = hazard;
            _speed = speed; _templates = templates; _construction = construction; _entities = entities;
            _entityRegistry = entityRegistry; _blocks = blocks; _camera = camera; _saver = saver;
            _settlement = settlement; _migration = migration;
        }

        public HttpResponse Handle(HttpRequest r)
        {
            if (r.Method == "GET")
            {
                switch (r.Path)
                {
                    case "/state": return State();
                    case "/districts": return Districts();
                    case "/housing": return Housing();
                    case "/buildings": return Buildings(r.Q("filter"));
                    case "/workplaces": return Workplaces();
                    case "/prefabs": return Prefabs(r.Q("filter"));
                    case "/unreachable": return Unreachable();
                    case "/": return Index();
                }
                return HttpResponse.NotFound(r.Path);
            }
            if (r.Method == "POST")
            {
                if (!r.IsJsonContentType())
                    return HttpResponse.Error(415, "POST requires Content-Type: application/json");
                Dictionary<string, object> body;
                try { body = JsonParser.ParseObject(r.Body); }
                catch (FormatException e) { return HttpResponse.Error(400, "invalid JSON body: " + e.Message); }
                try
                {
                    switch (r.Path)
                    {
                        case "/speed": return Speed(body);
                        case "/place": return Place(body);
                        case "/demolish": return Demolish(body);
                        case "/priority": return SetPriority(body);
                        case "/workers": return Workers(body);
                        case "/migrate": return Migrate(body);
                        case "/camera": return Camera(body);
                        case "/save": return Save(body);
                    }
                }
                catch (FormatException e) { return HttpResponse.Error(400, e.Message); }
                catch (ArgumentException e) { return HttpResponse.Error(400, e.Message); }
                return HttpResponse.NotFound(r.Path);
            }
            return HttpResponse.Error(405, "use GET or POST");
        }

        // ------------------------------------------------------------------ reads

        HttpResponse Index()
        {
            var w = new JsonWriter().Begin().Str("name", "Beaver Bridge").Str("version", BridgeServer.Version)
                .BeginArray("get");
            foreach (var p in new[] { "/ping", "/state", "/districts", "/housing", "/buildings?filter=", "/workplaces", "/prefabs?filter=", "/unreachable" }) w.Str(null, p);
            w.EndArray().BeginArray("post");
            foreach (var p in new[] { "/speed", "/place", "/demolish", "/priority", "/workers", "/migrate", "/camera", "/save" }) w.Str(null, p);
            return Ok(w.EndArray().End());
        }

        HttpResponse State()
        {
            var w = new JsonWriter().Begin()
                .Num("cycle", _cycle.Cycle)
                .Num("cycleDay", _cycle.CycleDay)
                .Num("dayNumber", _dayNight.DayNumber)
                .Num("hoursPassedToday", _dayNight.HoursPassedToday)
                .Bool("isDaytime", _dayNight.IsDaytime)
                .Bool("isHazardousWeather", _weather.IsHazardousWeather)
                .Str("hazardousWeather", _hazard.CurrentCycleHazardousWeather?.Id)
                .Num("hazardousWeatherDuration", _weather.HazardousWeatherDuration)
                .Num("hazardousWeatherStartCycleDay", _weather.HazardousWeatherStartCycleDay)
                .Num("cycleLengthInDays", _weather.CycleLengthInDays)
                .Num("speed", _speed.CurrentSpeed)
                .BeginArray("districts");
            foreach (var d in _districts.FinishedDistrictCenters) DistrictSummary(w, d);
            return Ok(w.EndArray().End());
        }

        HttpResponse Districts()
        {
            var w = new JsonWriter().Begin().BeginArray("districts");
            foreach (var d in _districts.AllDistrictCenters) DistrictSummary(w, d);
            return Ok(w.EndArray().End());
        }

        static void DistrictSummary(JsonWriter w, DistrictCenter d)
        {
            var pop = d.DistrictPopulation;
            w.BeginObject().Str("name", d.DistrictName).Coords("center", d.CenterCoordinates)
             .Num("adults", pop.NumberOfAdults).Num("children", pop.NumberOfChildren).Num("bots", pop.NumberOfBots)
             .EndObject();
        }

        HttpResponse Housing()
        {
            var w = new JsonWriter().Begin().BeginArray("districts");
            foreach (var d in _districts.FinishedDistrictCenters)
            {
                int homes = 0, adultSlots = 0, childSlots = 0, adults = 0, children = 0, freeAdult = 0;
                foreach (var h in d.DistrictBuildingRegistry.GetEnabledBuildings<Dwelling>())
                {
                    homes++;
                    adultSlots += h.AdultSlots; childSlots += h.ChildSlots;
                    adults += h.NumberOfAdultDwellers; children += h.NumberOfChildDwellers;
                    freeAdult += h.FreeAdultSlots;
                }
                var pop = d.DistrictPopulation;
                w.BeginObject().Str("name", d.DistrictName).Num("homes", homes)
                 .Num("adultSlots", adultSlots).Num("childSlots", childSlots)
                 .Num("adultsHoused", adults).Num("childrenHoused", children)
                 .Num("freeAdultSlots", freeAdult)
                 .Num("homelessAdults", Math.Max(0, pop.NumberOfAdults - adults))
                 .Num("homelessChildren", Math.Max(0, pop.NumberOfChildren - children))
                 .EndObject();
            }
            return Ok(w.EndArray().End());
        }

        HttpResponse Buildings(string filter)
        {
            var districtOf = DistrictIndex();
            var w = new JsonWriter().Begin().BeginArray("buildings");
            var count = 0;
            foreach (var e in _entityRegistry.Entities)
            {
                var block = e.GetComponent<BlockObject>();
                if (block == null) continue;
                var inventories = e.GetComponentsAllocating<Inventory>();
                if (inventories.Count == 0) continue;
                var template = TemplateOf(e);
                if (!Matches(template, filter)) continue;
                count++;
                w.BeginObject().Str("template", template).Coords("coords", block.Coordinates)
                 .Bool("finished", block.IsFinished)
                 .Str("district", districtOf.TryGetValue(e, out var dn) ? dn : null)
                 .Bool("reachable", Reachable(e))
                 .BeginArray("inventories");
                foreach (var inv in inventories)
                {
                    w.BeginObject().Str("name", inv.ComponentName).Num("capacity", inv.Capacity)
                     .Num("total", inv.TotalAmountInStock).Bool("input", inv.IsInput).Bool("output", inv.IsOutput)
                     .BeginArray("stock");
                    foreach (var g in inv.Stock) w.BeginObject().Str("good", g.GoodId).Num("amount", g.Amount).EndObject();
                    w.EndArray().EndObject();
                }
                w.EndArray().EndObject();
            }
            return Ok(w.EndArray().Num("count", count).End());
        }

        HttpResponse Workplaces()
        {
            var w = new JsonWriter().Begin().BeginArray("workplaces");
            foreach (var d in _districts.FinishedDistrictCenters)
            {
                foreach (var wp in d.DistrictBuildingRegistry.GetEnabledBuildings<Workplace>())
                {
                    var block = wp.GetComponent<BlockObject>();
                    var prio = wp.GetComponent<WorkplacePriority>();
                    w.BeginObject().Str("template", TemplateOf(wp)).Str("district", d.DistrictName);
                    if (block != null) w.Coords("coords", block.Coordinates);
                    w.Num("desired", wp.DesiredWorkers).Num("assigned", wp.NumberOfAssignedWorkers).Num("max", wp.MaxWorkers)
                     .Bool("understaffed", wp.Understaffed).Bool("overstaffed", wp.Overstaffed)
                     .Str("priority", prio != null ? prio.Priority.ToString() : null)
                     .EndObject();
                }
            }
            return Ok(w.EndArray().End());
        }

        HttpResponse Prefabs(string filter)
        {
            var w = new JsonWriter().Begin().BeginArray("prefabs");
            foreach (var bp in _templates.AllTemplates)
            {
                if (!bp.HasSpec<TemplateSpec>() || !bp.HasSpec<BlockObjectSpec>()) continue;
                var name = bp.GetSpec<TemplateSpec>().TemplateName;
                if (!Matches(name, filter)) continue;
                var spec = bp.GetSpec<BlockObjectSpec>();
                w.BeginObject().Str("name", name).Coords("size", spec.Size).Bool("flippable", spec.Flippable);
                if (spec.Entrance != null && spec.Entrance.HasEntrance) w.Coords("entrance", spec.Entrance.Coordinates);
                else w.Null("entrance");
                w.EndObject();
            }
            return Ok(w.EndArray().End());
        }

        HttpResponse Unreachable()
        {
            var w = new JsonWriter().Begin().BeginArray("unreachable");
            foreach (var e in _entityRegistry.Entities)
            {
                var block = e.GetComponent<BlockObject>();
                if (block == null || !block.IsFinished) continue;
                var flags = e.GetComponentsAllocating<IUnreachableEntity>();
                if (flags.Count == 0) continue;
                var unreachable = false;
                foreach (var f in flags) if (f.IsUnreachable()) { unreachable = true; break; }
                if (!unreachable) continue;
                w.BeginObject().Str("template", TemplateOf(e)).Coords("coords", block.Coordinates).EndObject();
            }
            return Ok(w.EndArray().End());
        }

        // ----------------------------------------------------------------- writes

        HttpResponse Speed(Dictionary<string, object> b)
        {
            var speed = JsonParser.Float(b, "speed");
            if (speed < 0) throw new FormatException("speed must be >= 0");
            _speed.ChangeSpeed(speed);
            // CurrentSpeed applies on LateUpdate, so echo the request rather than reading back.
            return Ok(new JsonWriter().Begin().Num("speed", speed).End());
        }

        HttpResponse Place(Dictionary<string, object> b)
        {
            var prefab = JsonParser.Str(b, "prefab") ?? throw new FormatException("missing 'prefab'");
            var coords = CoordsOf(b);
            var orientationText = JsonParser.Str(b, "orientation", "auto");

            var blueprint = FindTemplate(prefab);
            if (blueprint == null) return HttpResponse.Error(404, "no template named '" + prefab + "'");

            var orientations = orientationText.Equals("auto", StringComparison.OrdinalIgnoreCase)
                ? new[] { Orientation.Cw0, Orientation.Cw90, Orientation.Cw180, Orientation.Cw270 }
                : new[] { ParseOrientation(orientationText) };

            // Each attempt either throws, creating nothing, or succeeds. There is no
            // fallback kept from an earlier attempt, which was the old auto-orientation bug.
            string lastError = null;
            foreach (var o in orientations)
            {
                try
                {
                    var builder = new EntitySetup.Builder(blueprint);
                    var placement = new Placement(coords, o, FlipMode.Unflipped);
                    var created = _construction.CreateAsUnfinished(builder, placement);
                    return Ok(new JsonWriter().Begin().Str("prefab", prefab).Coords("coords", created.Coordinates)
                        .Str("orientation", o.ToString()).Bool("finished", created.IsFinished).End());
                }
                catch (Exception e) { lastError = e.GetType().Name + ": " + e.Message; }
            }
            return HttpResponse.Error(409, "placement rejected at " + Fmt(coords) + ": " + lastError);
        }

        HttpResponse Demolish(Dictionary<string, object> b)
        {
            var coords = CoordsOf(b);
            var objects = _blocks.GetObjectsAt(coords);
            if (objects.Count == 0) return HttpResponse.Error(404, "nothing at " + Fmt(coords));
            var w = new JsonWriter().Begin().BeginArray("deleted");
            foreach (var o in objects.ToList())
            {
                w.BeginObject().Str("template", TemplateOf(o)).Coords("coords", o.Coordinates).EndObject();
                _entities.Delete(o);
            }
            return Ok(w.EndArray().End());
        }

        HttpResponse SetPriority(Dictionary<string, object> b)
        {
            var coords = CoordsOf(b);
            var text = JsonParser.Str(b, "priority") ?? throw new FormatException("missing 'priority'");
            if (!Enum.TryParse<Priority>(text, true, out var priority))
                throw new FormatException("priority must be one of VeryLow, Low, Normal, High, VeryHigh");
            var wp = _blocks.GetFirstObjectWithComponentAt<WorkplacePriority>(coords);
            if (wp != null) { wp.SetPriority(priority); return Ok(PriorityJson("workplace", coords, priority)); }
            var bp = _blocks.GetFirstObjectWithComponentAt<BuilderPrioritizable>(coords);
            if (bp != null) { bp.SetPriority(priority); return Ok(PriorityJson("construction", coords, priority)); }
            return HttpResponse.Error(404, "no prioritizable building at " + Fmt(coords));
        }

        HttpResponse Workers(Dictionary<string, object> b)
        {
            var coords = CoordsOf(b);
            var desired = JsonParser.Int(b, "desired");
            var wp = _blocks.GetFirstObjectWithComponentAt<Workplace>(coords);
            if (wp == null) return HttpResponse.Error(404, "no workplace at " + Fmt(coords));
            // DesiredWorkers has no public setter; step towards the target and stop when it stops moving.
            for (var guard = 0; guard < 64 && wp.DesiredWorkers != desired; guard++)
            {
                var before = wp.DesiredWorkers;
                if (wp.DesiredWorkers < desired) wp.IncreaseDesiredWorkers(); else wp.DecreaseDesiredWorkers();
                if (wp.DesiredWorkers == before) break;
            }
            return Ok(new JsonWriter().Begin().Coords("coords", coords).Num("requested", desired)
                .Num("desired", wp.DesiredWorkers).Num("max", wp.MaxWorkers).End());
        }

        HttpResponse Migrate(Dictionary<string, object> b)
        {
            var from = FindDistrict(JsonParser.Str(b, "from") ?? throw new FormatException("missing 'from'"));
            var to = FindDistrict(JsonParser.Str(b, "to") ?? throw new FormatException("missing 'to'"));
            if (from == null || to == null) return HttpResponse.Error(404, "unknown district name");
            if (from == to) throw new FormatException("'from' and 'to' are the same district");
            var adults = JsonParser.Int(b, "adults", 0);
            var children = JsonParser.Int(b, "children", 0);
            var bots = JsonParser.Int(b, "bots", 0);
            var pop = from.DistrictPopulation;
            var movedAdults = Move(pop.Adults.Cast<BaseComponent>().ToList(), to, adults);
            var movedChildren = Move(pop.Children.Cast<BaseComponent>().ToList(), to, children);
            var movedBots = Move(pop.Bots.Cast<BaseComponent>().ToList(), to, bots);
            return Ok(new JsonWriter().Begin().Str("from", from.DistrictName).Str("to", to.DistrictName)
                .Num("adults", movedAdults).Num("children", movedChildren).Num("bots", movedBots).End());
        }

        int Move(List<BaseComponent> candidates, DistrictCenter to, int requested)
        {
            if (requested <= 0 || candidates.Count == 0) return 0;
            var n = Math.Min(requested, candidates.Count);
            _migration.Migrate(candidates, to, n);
            return n;
        }

        HttpResponse Camera(Dictionary<string, object> b)
        {
            var coords = CoordsOf(b);
            _camera.MoveTargetTo(CoordinateSystem.GridToWorldCentered(coords));
            if (b.ContainsKey("zoom")) _camera.ZoomLevel = JsonParser.Float(b, "zoom");
            return Ok(new JsonWriter().Begin().Coords("target", coords).Num("zoom", _camera.ZoomLevel).End());
        }

        HttpResponse Save(Dictionary<string, object> b)
        {
            var name = JsonParser.Str(b, "name") ?? throw new FormatException("missing 'name'");
            if (name.Trim().Length == 0 || name.IndexOfAny(System.IO.Path.GetInvalidFileNameChars()) >= 0)
                throw new FormatException("'name' is not a valid save name");
            var reference = new SaveReference(name, _settlement.SettlementReference);
            _saver.QueueSaveSkippingNameValidation(reference, () => { });
            return Ok(new JsonWriter().Begin().Str("queued", name).End());
        }

        // ---------------------------------------------------------------- helpers

        static HttpResponse Ok(JsonWriter w) => HttpResponse.Json(200, w.ToString());
        static HttpResponse Ok(string json) => HttpResponse.Json(200, json);

        static string PriorityJson(string kind, Vector3Int coords, Priority p) =>
            new JsonWriter().Begin().Str("kind", kind).Coords("coords", coords).Str("priority", p.ToString()).End().ToString();

        static Vector3Int CoordsOf(Dictionary<string, object> b) =>
            new Vector3Int(JsonParser.Int(b, "x"), JsonParser.Int(b, "y"), JsonParser.Int(b, "z"));

        static string Fmt(Vector3Int c) => "(" + c.x + "," + c.y + "," + c.z + ")";

        static Orientation ParseOrientation(string text)
        {
            if (Enum.TryParse<Orientation>(text, true, out var o)) return o;
            switch (text.Trim())
            {
                case "0": return Orientation.Cw0;
                case "90": case "1": return Orientation.Cw90;
                case "180": case "2": return Orientation.Cw180;
                case "270": case "3": return Orientation.Cw270;
            }
            throw new FormatException("orientation must be auto, Cw0, Cw90, Cw180, Cw270 or 0/90/180/270");
        }

        static bool Matches(string template, string filter) =>
            string.IsNullOrEmpty(filter) || (template != null && template.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0);

        /// <summary>The GameObject name is "<Template>(Clone)"; strip the suffix.</summary>
        static string TemplateOf(BaseComponent c)
        {
            var n = c.Name ?? "";
            return n.EndsWith("(Clone)", StringComparison.Ordinal) ? n.Substring(0, n.Length - 7) : n;
        }

        static bool Reachable(BaseComponent e)
        {
            var a = e.GetComponent<Accessible>();
            return a == null || a.ValidAccessible;
        }

        Blueprint FindTemplate(string name)
        {
            foreach (var bp in _templates.AllTemplates)
                if (bp.HasSpec<TemplateSpec>() && bp.GetSpec<TemplateSpec>().IsNamed(name)) return bp;
            return null;
        }

        DistrictCenter FindDistrict(string name)
        {
            foreach (var d in _districts.AllDistrictCenters)
                if (string.Equals(d.DistrictName, name, StringComparison.OrdinalIgnoreCase)) return d;
            return null;
        }

        /// <summary>Entity → district name, built from each district's own building registry.</summary>
        Dictionary<EntityComponent, string> DistrictIndex()
        {
            var map = new Dictionary<EntityComponent, string>();
            foreach (var d in _districts.FinishedDistrictCenters)
                foreach (var building in d.DistrictBuildingRegistry.GetEnabledBuildings<Timberborn.Buildings.Building>())
                {
                    var e = building.GetComponent<EntityComponent>();
                    if (e != null && !map.ContainsKey(e)) map[e] = d.DistrictName;
                }
            return map;
        }
    }
}
