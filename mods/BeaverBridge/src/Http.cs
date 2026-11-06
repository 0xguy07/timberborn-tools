using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace BeaverBridge
{
    /// <summary>Just enough HTTP/1.1 to serve a local JSON API. No keep-alive, no chunking.</summary>
    public sealed class HttpRequest
    {
        public string Method;
        public string Path;
        public Dictionary<string, string> Query = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, string> Headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public string Body = "";

        public string Q(string key, string fallback = null) => Query.TryGetValue(key, out var v) ? v : fallback;

        /// <summary>
        /// True when the request declares a JSON body. POST handlers require this: a
        /// browser cannot send a cross-origin request with this content type without a
        /// CORS preflight, and the bridge never answers preflights, so a web page you
        /// happen to have open cannot drive the game through the bridge.
        /// </summary>
        public bool IsJsonContentType()
        {
            if (!Headers.TryGetValue("Content-Type", out var ct) || ct == null) return false;
            var semi = ct.IndexOf(';');
            var mime = (semi < 0 ? ct : ct.Substring(0, semi)).Trim();
            return mime.Equals("application/json", StringComparison.OrdinalIgnoreCase);
        }

        public static HttpRequest Read(Stream stream)
        {
            var buffer = new MemoryStream();
            var one = new byte[1];
            // Read until the blank line that ends the headers.
            while (true)
            {
                var n = stream.Read(one, 0, 1);
                if (n == 0) return buffer.Length == 0 ? null : throw new IOException("connection closed mid-headers");
                buffer.WriteByte(one[0]);
                if (buffer.Length > 65536) throw new IOException("headers too large");
                if (EndsWithBlankLine(buffer)) break;
            }
            var head = Encoding.ASCII.GetString(buffer.GetBuffer(), 0, (int)buffer.Length);
            var lines = head.Split(new[] { "\r\n" }, StringSplitOptions.None);
            var parts = lines[0].Split(' ');
            if (parts.Length < 2) throw new IOException("malformed request line");

            var req = new HttpRequest { Method = parts[0].ToUpperInvariant() };
            var target = parts[1];
            var qi = target.IndexOf('?');
            req.Path = qi < 0 ? target : target.Substring(0, qi);
            if (qi >= 0)
            {
                foreach (var pair in target.Substring(qi + 1).Split('&'))
                {
                    if (pair.Length == 0) continue;
                    var eq = pair.IndexOf('=');
                    var k = Uri.UnescapeDataString(eq < 0 ? pair : pair.Substring(0, eq)).Replace('+', ' ');
                    var v = eq < 0 ? "" : Uri.UnescapeDataString(pair.Substring(eq + 1).Replace('+', ' '));
                    req.Query[k] = v;
                }
            }
            for (var i = 1; i < lines.Length; i++)
            {
                var c = lines[i].IndexOf(':');
                if (c > 0) req.Headers[lines[i].Substring(0, c).Trim()] = lines[i].Substring(c + 1).Trim();
            }
            if (req.Headers.TryGetValue("Content-Length", out var lenText) && int.TryParse(lenText, out var len) && len > 0)
            {
                if (len > 1 << 20) throw new IOException("body too large");
                var body = new byte[len];
                var read = 0;
                while (read < len)
                {
                    var n = stream.Read(body, read, len - read);
                    if (n <= 0) throw new IOException("connection closed mid-body");
                    read += n;
                }
                req.Body = Encoding.UTF8.GetString(body);
            }
            return req;
        }

        static bool EndsWithBlankLine(MemoryStream s)
        {
            if (s.Length < 4) return false;
            var b = s.GetBuffer();
            var n = (int)s.Length;
            return b[n - 4] == '\r' && b[n - 3] == '\n' && b[n - 2] == '\r' && b[n - 1] == '\n';
        }
    }

    public sealed class HttpResponse
    {
        public int Status;
        public string ContentType = "application/json; charset=utf-8";
        public string Body;

        public static HttpResponse Json(int status, string json) => new HttpResponse { Status = status, Body = json };

        public static HttpResponse Error(int status, string message) =>
            Json(status, new JsonWriter().Begin().Str("error", message).Num("status", status).End().ToString());

        public static HttpResponse NotFound(string path) => Error(404, "no such endpoint: " + path);

        public byte[] ToBytes()
        {
            var body = Encoding.UTF8.GetBytes(Body ?? "");
            var head = "HTTP/1.1 " + Status + " " + Reason(Status) + "\r\n" +
                       "Content-Type: " + ContentType + "\r\n" +
                       "Content-Length: " + body.Length + "\r\n" +
                       "Connection: close\r\n\r\n";
            var headBytes = Encoding.ASCII.GetBytes(head);
            var all = new byte[headBytes.Length + body.Length];
            Buffer.BlockCopy(headBytes, 0, all, 0, headBytes.Length);
            Buffer.BlockCopy(body, 0, all, headBytes.Length, body.Length);
            return all;
        }

        static string Reason(int status)
        {
            switch (status)
            {
                case 200: return "OK";
                case 400: return "Bad Request";
                case 404: return "Not Found";
                case 405: return "Method Not Allowed";
                case 409: return "Conflict";
                case 415: return "Unsupported Media Type";
                case 500: return "Internal Server Error";
                case 503: return "Service Unavailable";
                case 504: return "Gateway Timeout";
                default: return "Status";
            }
        }
    }
}
