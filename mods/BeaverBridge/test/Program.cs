// Test harness for Json.cs and Http.cs. Run: dotnet run --project mods/BeaverBridge/test
using System;
using System.IO;
using System.Text;
using BeaverBridge;
int fails = 0;
void Check(bool ok, string what) { if (!ok) { fails++; Console.WriteLine("FAIL " + what); } else Console.WriteLine("ok   " + what); }

// JSON writer
var j = new JsonWriter().Begin().Str("s", "a\"b\\c\n").Num("i", 42).Num("f", 1.23456).Bool("b", true).Null("n")
    .BeginArray("arr").Num(null, 1).Str(null, "x").EndArray().Coords("c", new UnityEngine.Vector3Int(1,2,3)).End().ToString();
Check(j == "{\"s\":\"a\\\"b\\\\c\\n\",\"i\":42,\"f\":1.235,\"b\":true,\"n\":null,\"arr\":[1,\"x\"],\"c\":{\"x\":1,\"y\":2,\"z\":3}}", "writer output: " + j);

// JSON parser round trip
var o = JsonParser.ParseObject(j);
Check((string)o["s"] == "a\"b\\c\n", "parse escaped string");
Check(JsonParser.Int(o, "i") == 42, "parse int");
Check(Math.Abs(JsonParser.Float(o, "f") - 1.235f) < 1e-5, "parse float");
Check((bool)o["b"] == true && o["n"] == null, "parse bool/null");
Check(o["arr"] is System.Collections.Generic.List<object> l && l.Count == 2 && (string)l[1] == "x", "parse array");
Check(JsonParser.Int(o, "missing", 7) == 7, "int fallback");
Check(JsonParser.ParseObject("").Count == 0, "empty body is empty object");
try { JsonParser.ParseObject("[1]"); Check(false, "array body rejected"); } catch (FormatException) { Check(true, "array body rejected"); }
try { JsonParser.ParseObject("{\"a\":}"); Check(false, "bad json rejected"); } catch (FormatException) { Check(true, "bad json rejected"); }
try { JsonParser.Int(JsonParser.ParseObject("{\"x\":\"abc\"}"), "x"); Check(false, "non-int rejected"); } catch (FormatException) { Check(true, "non-int rejected"); }
Check(JsonParser.Int(JsonParser.ParseObject("{\"x\":\"12\"}"), "x") == 12, "numeric string accepted");

// HTTP request parsing
var raw = "POST /place?filter=Lod%20ge&flag HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 18\r\n\r\n{\"prefab\":\"Lodge\"}";
var req = HttpRequest.Read(new MemoryStream(Encoding.UTF8.GetBytes(raw)));
Check(req.Method == "POST" && req.Path == "/place", "request line");
Check(req.Q("filter") == "Lod ge" && req.Q("flag") == "" && req.Q("nope", "d") == "d", "query parsing");
Check(req.Headers["content-type"] == "application/json", "headers case-insensitive");
Check(req.Body == "{\"prefab\":\"Lodge\"}", "body by content-length: " + req.Body);
var get = HttpRequest.Read(new MemoryStream(Encoding.ASCII.GetBytes("GET /ping HTTP/1.1\r\n\r\n")));
Check(get.Method == "GET" && get.Path == "/ping" && get.Body == "", "GET without body");
Check(HttpRequest.Read(new MemoryStream(new byte[0])) == null, "empty connection returns null");

// HTTP response bytes
var resp = Encoding.UTF8.GetString(HttpResponse.Error(404, "nope").ToBytes());
Check(resp.StartsWith("HTTP/1.1 404 Not Found\r\n") && resp.Contains("Content-Length: ") && resp.EndsWith("{\"error\":\"nope\",\"status\":404}"), "response framing");
var body = resp.Substring(resp.IndexOf("\r\n\r\n") + 4);
var declared = int.Parse(System.Text.RegularExpressions.Regex.Match(resp, "Content-Length: (\\d+)").Groups[1].Value);
Check(declared == Encoding.UTF8.GetByteCount(body), "content-length matches body");

Console.WriteLine(fails == 0 ? "ALL PASSED" : fails + " FAILED");
return fails == 0 ? 0 : 1;
