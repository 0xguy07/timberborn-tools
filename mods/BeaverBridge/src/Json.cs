using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace BeaverBridge
{
    /// <summary>
    /// Hand-rolled JSON so the mod does not depend on the game's bundled
    /// Newtonsoft or on System.Text.Json, neither of which is a safe reference
    /// from netstandard2.1 inside the game's Mono runtime.
    /// </summary>
    public sealed class JsonWriter
    {
        readonly StringBuilder _sb = new StringBuilder();
        readonly Stack<bool> _first = new Stack<bool>();

        public JsonWriter Begin() { Open('{'); return this; }
        public JsonWriter End() { Close('}'); return this; }
        public JsonWriter BeginArray(string key = null) { Key(key); Open('['); return this; }
        public JsonWriter EndArray() { Close(']'); return this; }
        public JsonWriter BeginObject(string key = null) { Key(key); Open('{'); return this; }
        public JsonWriter EndObject() { Close('}'); return this; }

        public JsonWriter Str(string key, string value) { Key(key); Quote(value); return this; }
        public JsonWriter Num(string key, long value) { Key(key); _sb.Append(value.ToString(CultureInfo.InvariantCulture)); return this; }
        public JsonWriter Num(string key, double value)
        {
            Key(key);
            if (double.IsNaN(value) || double.IsInfinity(value)) _sb.Append("null");
            else _sb.Append(Math.Round(value, 3).ToString("0.###", CultureInfo.InvariantCulture));
            return this;
        }
        public JsonWriter Bool(string key, bool value) { Key(key); _sb.Append(value ? "true" : "false"); return this; }
        public JsonWriter Null(string key) { Key(key); _sb.Append("null"); return this; }
        public JsonWriter Raw(string key, string json) { Key(key); _sb.Append(json); return this; }

        public JsonWriter Coords(string key, UnityEngine.Vector3Int c)
        {
            BeginObject(key).Num("x", c.x).Num("y", c.y).Num("z", c.z).EndObject();
            return this;
        }

        public override string ToString() => _sb.ToString();

        void Open(char c)
        {
            _sb.Append(c);
            _first.Push(true);
        }
        void Close(char c)
        {
            _first.Pop();
            _sb.Append(c);
        }
        void Key(string key)
        {
            if (_first.Count > 0)
            {
                if (_first.Peek()) { _first.Pop(); _first.Push(false); }
                else _sb.Append(',');
            }
            if (key != null) { Quote(key); _sb.Append(':'); }
        }
        void Quote(string s)
        {
            if (s == null) { _sb.Append("null"); return; }
            _sb.Append('"');
            foreach (var ch in s)
            {
                switch (ch)
                {
                    case '"': _sb.Append("\\\""); break;
                    case '\\': _sb.Append("\\\\"); break;
                    case '\n': _sb.Append("\\n"); break;
                    case '\r': _sb.Append("\\r"); break;
                    case '\t': _sb.Append("\\t"); break;
                    default:
                        if (ch < 0x20) _sb.Append("\\u").Append(((int)ch).ToString("x4"));
                        else _sb.Append(ch);
                        break;
                }
            }
            _sb.Append('"');
        }
    }

    /// <summary>Parses a JSON document into Dictionary / List / string / double / bool / null.</summary>
    public static class JsonParser
    {
        public static Dictionary<string, object> ParseObject(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return new Dictionary<string, object>();
            var p = new Reader(text);
            p.SkipWs();
            var v = p.Value();
            p.SkipWs();
            if (!p.End) throw new FormatException("trailing characters after JSON value");
            return v as Dictionary<string, object> ?? throw new FormatException("JSON body must be an object");
        }

        public static string Str(Dictionary<string, object> o, string key, string fallback = null) =>
            o.TryGetValue(key, out var v) && v != null ? Convert.ToString(v, CultureInfo.InvariantCulture) : fallback;

        public static int Int(Dictionary<string, object> o, string key, int? fallback = null)
        {
            if (o.TryGetValue(key, out var v) && v != null)
            {
                if (v is double d) return (int)Math.Round(d);
                if (v is string s && int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out var i)) return i;
                throw new FormatException("'" + key + "' must be an integer");
            }
            if (fallback.HasValue) return fallback.Value;
            throw new FormatException("missing '" + key + "'");
        }

        public static float Float(Dictionary<string, object> o, string key, float? fallback = null)
        {
            if (o.TryGetValue(key, out var v) && v != null)
            {
                if (v is double d) return (float)d;
                if (v is string s && float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var f)) return f;
                throw new FormatException("'" + key + "' must be a number");
            }
            if (fallback.HasValue) return fallback.Value;
            throw new FormatException("missing '" + key + "'");
        }

        sealed class Reader
        {
            readonly string _s;
            int _i;
            public Reader(string s) { _s = s; }
            public bool End => _i >= _s.Length;
            char Peek => _s[_i];

            public void SkipWs() { while (!End && char.IsWhiteSpace(Peek)) _i++; }

            public object Value()
            {
                SkipWs();
                if (End) throw new FormatException("unexpected end of JSON");
                switch (Peek)
                {
                    case '{': return Object();
                    case '[': return Array();
                    case '"': return String();
                    case 't': Expect("true"); return true;
                    case 'f': Expect("false"); return false;
                    case 'n': Expect("null"); return null;
                    default: return Number();
                }
            }

            Dictionary<string, object> Object()
            {
                var o = new Dictionary<string, object>();
                _i++; SkipWs();
                if (!End && Peek == '}') { _i++; return o; }
                while (true)
                {
                    SkipWs();
                    if (End || Peek != '"') throw new FormatException("expected key at " + _i);
                    var k = String();
                    SkipWs();
                    if (End || Peek != ':') throw new FormatException("expected ':' at " + _i);
                    _i++;
                    o[k] = Value();
                    SkipWs();
                    if (End) throw new FormatException("unterminated object");
                    if (Peek == ',') { _i++; continue; }
                    if (Peek == '}') { _i++; return o; }
                    throw new FormatException("expected ',' or '}' at " + _i);
                }
            }

            List<object> Array()
            {
                var a = new List<object>();
                _i++; SkipWs();
                if (!End && Peek == ']') { _i++; return a; }
                while (true)
                {
                    a.Add(Value());
                    SkipWs();
                    if (End) throw new FormatException("unterminated array");
                    if (Peek == ',') { _i++; continue; }
                    if (Peek == ']') { _i++; return a; }
                    throw new FormatException("expected ',' or ']' at " + _i);
                }
            }

            string String()
            {
                var sb = new StringBuilder();
                _i++;
                while (true)
                {
                    if (End) throw new FormatException("unterminated string");
                    var c = _s[_i++];
                    if (c == '"') return sb.ToString();
                    if (c != '\\') { sb.Append(c); continue; }
                    if (End) throw new FormatException("bad escape");
                    var e = _s[_i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (_i + 4 > _s.Length) throw new FormatException("bad \\u escape");
                            sb.Append((char)int.Parse(_s.Substring(_i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                            _i += 4;
                            break;
                        default: throw new FormatException("bad escape \\" + e);
                    }
                }
            }

            double Number()
            {
                var start = _i;
                while (!End && (char.IsDigit(Peek) || Peek == '-' || Peek == '+' || Peek == '.' || Peek == 'e' || Peek == 'E')) _i++;
                if (start == _i) throw new FormatException("unexpected character '" + Peek + "' at " + _i);
                return double.Parse(_s.Substring(start, _i - start), NumberStyles.Float, CultureInfo.InvariantCulture);
            }

            void Expect(string word)
            {
                if (string.CompareOrdinal(_s, _i, word, 0, word.Length) != 0) throw new FormatException("expected " + word + " at " + _i);
                _i += word.Length;
            }
        }
    }
}
