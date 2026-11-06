using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Timberborn.SingletonSystem;
using UnityEngine;

namespace BeaverBridge
{
    /// <summary>
    /// Minimal HTTP/1.1 server on a background thread. Every request that touches
    /// game state is turned into a Job and executed on Unity's main thread from
    /// UpdateSingleton, which runs once per rendered frame even while the game is
    /// paused. Only /ping is answered directly on the socket thread.
    /// </summary>
    public class BridgeServer : ILoadableSingleton, IUpdatableSingleton, IUnloadableSingleton
    {
        public const string Version = "0.9.0";
        const int DefaultPort = 7777;
        const int JobTimeoutMs = 5000;
        const int MaxJobsPerFrame = 64;

        readonly GameApi _api;
        readonly ConcurrentQueue<Job> _jobs = new ConcurrentQueue<Job>();
        TcpListener _listener;
        Thread _thread;
        volatile bool _running;
        volatile bool _pumpRunning;

        public BridgeServer(GameApi api)
        {
            _api = api;
        }

        public void Load()
        {
            var port = DefaultPort;
            var env = Environment.GetEnvironmentVariable("BEAVER_BRIDGE_PORT");
            if (!string.IsNullOrEmpty(env) && int.TryParse(env, out var p) && p > 0 && p < 65536) port = p;

            try
            {
                _listener = new TcpListener(IPAddress.Loopback, port);
                _listener.Start();
            }
            catch (Exception e)
            {
                Debug.LogError("[BeaverBridge] cannot listen on 127.0.0.1:" + port + ": " + e.Message);
                _listener = null;
                return;
            }
            _running = true;
            _thread = new Thread(AcceptLoop) { IsBackground = true, Name = "BeaverBridge" };
            _thread.Start();
            Debug.Log("[BeaverBridge] v" + Version + " listening on http://127.0.0.1:" + port + "/");
        }

        public void UpdateSingleton()
        {
            _pumpRunning = true;
            var n = 0;
            while (n++ < MaxJobsPerFrame && _jobs.TryDequeue(out var job))
            {
                try { job.Response = _api.Handle(job.Request); }
                catch (Exception e) { job.Response = HttpResponse.Error(500, e.GetType().Name + ": " + e.Message); }
                finally { job.Done.Set(); }
            }
        }

        public void Unload()
        {
            _running = false;
            _pumpRunning = false;
            try { _listener?.Stop(); } catch { }
            while (_jobs.TryDequeue(out var job))
            {
                job.Response = HttpResponse.Error(503, "game context unloading");
                job.Done.Set();
            }
        }

        void AcceptLoop()
        {
            while (_running)
            {
                TcpClient client;
                try { client = _listener.AcceptTcpClient(); }
                catch { if (_running) continue; break; }
                ThreadPool.QueueUserWorkItem(_ => Serve(client));
            }
        }

        void Serve(TcpClient client)
        {
            using (client)
            {
                client.ReceiveTimeout = 10000;
                client.SendTimeout = 10000;
                NetworkStream stream;
                try { stream = client.GetStream(); } catch { return; }
                HttpRequest request;
                try { request = HttpRequest.Read(stream); }
                catch (Exception e) { Write(stream, HttpResponse.Error(400, "bad request: " + e.Message)); return; }
                if (request == null) return;

                HttpResponse response;
                if (request.Path == "/ping")
                {
                    response = HttpResponse.Json(200, new JsonWriter()
                        .Begin().Str("version", Version).Bool("pumpRunning", _pumpRunning).End().ToString());
                }
                else
                {
                    var job = new Job(request);
                    _jobs.Enqueue(job);
                    response = job.Done.Wait(JobTimeoutMs)
                        ? job.Response
                        : HttpResponse.Error(504, "main thread did not answer within " + JobTimeoutMs + " ms (is a game loaded?)");
                }
                Write(stream, response);
            }
        }

        static void Write(Stream stream, HttpResponse response)
        {
            try
            {
                var bytes = response.ToBytes();
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush();
            }
            catch { }
        }

        sealed class Job
        {
            public readonly HttpRequest Request;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
            public HttpResponse Response;
            public Job(HttpRequest request) { Request = request; }
        }
    }
}
