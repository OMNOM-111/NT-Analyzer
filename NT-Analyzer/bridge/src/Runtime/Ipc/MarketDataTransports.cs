using System;
using System.IO;
using System.IO.Pipes;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using NTAnalyzerBridge.Util;

namespace NTAnalyzerBridge.Runtime.Ipc
{
    internal interface IMarketDataTransport : IDisposable
    {
        string Name { get; }
        bool IsConnected { get; }
        void Connect(string authToken, string connectionId, string bridgeVersion);
        void SendUtf8(string jsonObject);
        string ReceiveUtf8(int timeoutMs);
        void CloseGracefully();
    }

    internal abstract class LengthPrefixedTransportBase
    {
        protected static byte[] EncodeFrame(string jsonObject)
        {
            byte[] body = Encoding.UTF8.GetBytes(jsonObject);
            byte[] frame = new byte[4 + body.Length];
            frame[0] = (byte)((body.Length >> 24) & 0xff);
            frame[1] = (byte)((body.Length >> 16) & 0xff);
            frame[2] = (byte)((body.Length >> 8) & 0xff);
            frame[3] = (byte)(body.Length & 0xff);
            Buffer.BlockCopy(body, 0, frame, 4, body.Length);
            return frame;
        }

        protected static string ReadFrame(Stream stream, int timeoutMs)
        {
            if (stream.CanTimeout)
            {
                stream.ReadTimeout = timeoutMs;
            }
            byte[] header = ReadExact(stream, 4);
            int length = (header[0] << 24) | (header[1] << 16) | (header[2] << 8) | header[3];
            if (length <= 0 || length > 1024 * 1024)
                throw new InvalidDataException("invalid IPC frame length: " + length);
            byte[] body = ReadExact(stream, length);
            return Encoding.UTF8.GetString(body);
        }

        private static byte[] ReadExact(Stream stream, int size)
        {
            byte[] buffer = new byte[size];
            int offset = 0;
            while (offset < size)
            {
                int read = stream.Read(buffer, offset, size - offset);
                if (read <= 0) throw new EndOfStreamException("IPC stream closed");
                offset += read;
            }
            return buffer;
        }
    }

    /// <summary>Default transport: authenticated length-prefixed JSON over 127.0.0.1 TCP.</summary>
    internal sealed class TcpMarketDataTransport : LengthPrefixedTransportBase, IMarketDataTransport
    {
        private readonly string _host;
        private readonly int _port;
        private TcpClient _client;
        private NetworkStream _stream;

        public TcpMarketDataTransport(string host, int port)
        {
            if (host != "127.0.0.1" && !string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("IPC TCP host must be localhost");
            _host = "127.0.0.1";
            _port = port;
        }

        public string Name { get { return "tcp"; } }
        public bool IsConnected { get { return _client != null && _client.Connected; } }

        public void Connect(string authToken, string connectionId, string bridgeVersion)
        {
            _client = new TcpClient();
            _client.Connect(_host, _port);
            _stream = _client.GetStream();
            string hello = "{\"type\":\"hello\",\"protocol_version\":1,\"auth_token\":\""
                + Escape(authToken) + "\",\"connection_id\":\"" + Escape(connectionId)
                + "\",\"bridge_version\":\"" + Escape(bridgeVersion)
                + "\",\"transport\":\"tcp\"}";
            SendUtf8(hello);
            string welcome = ReceiveUtf8(5000);
            if (welcome.IndexOf("\"type\":\"welcome\"", StringComparison.Ordinal) < 0)
                throw new InvalidOperationException("IPC hello rejected: " + welcome);
        }

        public void SendUtf8(string jsonObject)
        {
            if (_stream == null) throw new InvalidOperationException("IPC not connected");
            byte[] frame = EncodeFrame(jsonObject);
            _stream.Write(frame, 0, frame.Length);
        }

        public string ReceiveUtf8(int timeoutMs)
        {
            if (_stream == null) throw new InvalidOperationException("IPC not connected");
            return ReadFrame(_stream, timeoutMs);
        }

        public void CloseGracefully()
        {
            try
            {
                if (IsConnected) SendUtf8("{\"type\":\"goodbye\"}");
            }
            catch { }
            Dispose();
        }

        public void Dispose()
        {
            try { if (_stream != null) _stream.Dispose(); } catch { }
            try { if (_client != null) _client.Close(); } catch { }
            _stream = null;
            _client = null;
        }

        private static string Escape(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }

    /// <summary>Windows Named Pipe transport with the same frame protocol.</summary>
    internal sealed class NamedPipeMarketDataTransport : LengthPrefixedTransportBase, IMarketDataTransport
    {
        private readonly string _pipeName;
        private NamedPipeClientStream _pipe;

        public NamedPipeMarketDataTransport(string pipeName)
        {
            if (string.IsNullOrWhiteSpace(pipeName))
                throw new ArgumentException("pipe name required");
            _pipeName = pipeName;
        }

        public string Name { get { return "named_pipe"; } }
        public bool IsConnected { get { return _pipe != null && _pipe.IsConnected; } }

        public void Connect(string authToken, string connectionId, string bridgeVersion)
        {
            string name = _pipeName;
            // Accept either full \\.\pipe\name or bare name.
            const string prefix = @"\\.\pipe\";
            if (name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                name = name.Substring(prefix.Length);
            _pipe = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
            _pipe.Connect(5000);
            string hello = "{\"type\":\"hello\",\"protocol_version\":1,\"auth_token\":\""
                + Escape(authToken) + "\",\"connection_id\":\"" + Escape(connectionId)
                + "\",\"bridge_version\":\"" + Escape(bridgeVersion)
                + "\",\"transport\":\"named_pipe\"}";
            SendUtf8(hello);
            string welcome = ReceiveUtf8(5000);
            if (welcome.IndexOf("\"type\":\"welcome\"", StringComparison.Ordinal) < 0)
                throw new InvalidOperationException("IPC hello rejected: " + welcome);
        }

        public void SendUtf8(string jsonObject)
        {
            if (_pipe == null) throw new InvalidOperationException("IPC not connected");
            byte[] frame = EncodeFrame(jsonObject);
            _pipe.Write(frame, 0, frame.Length);
            _pipe.Flush();
        }

        public string ReceiveUtf8(int timeoutMs)
        {
            if (_pipe == null) throw new InvalidOperationException("IPC not connected");
            return ReadFrame(_pipe, timeoutMs);
        }

        public void CloseGracefully()
        {
            try { if (IsConnected) SendUtf8("{\"type\":\"goodbye\"}"); } catch { }
            Dispose();
        }

        public void Dispose()
        {
            try { if (_pipe != null) _pipe.Dispose(); } catch { }
            _pipe = null;
        }

        private static string Escape(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }

    /// <summary>
    /// WebSocket transport. Application payload is still the JSON object;
    /// length-prefix is not used on the wire (WS frames provide framing).
    /// </summary>
    internal sealed class WebSocketMarketDataTransport : IMarketDataTransport
    {
        private readonly Uri _uri;
        private ClientWebSocket _socket;
        private readonly ArraySegment<byte> _buffer = new ArraySegment<byte>(new byte[64 * 1024]);

        public WebSocketMarketDataTransport(string url)
        {
            if (string.IsNullOrWhiteSpace(url)) throw new ArgumentException("ws url required");
            _uri = new Uri(url);
            if (_uri.Host != "127.0.0.1" && !string.Equals(_uri.Host, "localhost", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("IPC WebSocket host must be localhost");
        }

        public string Name { get { return "websocket"; } }
        public bool IsConnected
        {
            get { return _socket != null && _socket.State == WebSocketState.Open; }
        }

        public void Connect(string authToken, string connectionId, string bridgeVersion)
        {
            _socket = new ClientWebSocket();
            _socket.ConnectAsync(_uri, CancellationToken.None).GetAwaiter().GetResult();
            string hello = "{\"type\":\"hello\",\"protocol_version\":1,\"auth_token\":\""
                + Escape(authToken) + "\",\"connection_id\":\"" + Escape(connectionId)
                + "\",\"bridge_version\":\"" + Escape(bridgeVersion)
                + "\",\"transport\":\"websocket\"}";
            SendUtf8(hello);
            string welcome = ReceiveUtf8(5000);
            if (welcome.IndexOf("\"type\":\"welcome\"", StringComparison.Ordinal) < 0)
                throw new InvalidOperationException("IPC hello rejected: " + welcome);
        }

        public void SendUtf8(string jsonObject)
        {
            if (!IsConnected) throw new InvalidOperationException("IPC not connected");
            byte[] body = Encoding.UTF8.GetBytes(jsonObject);
            _socket.SendAsync(new ArraySegment<byte>(body), WebSocketMessageType.Text, true, CancellationToken.None)
                .GetAwaiter().GetResult();
        }

        public string ReceiveUtf8(int timeoutMs)
        {
            if (!IsConnected) throw new InvalidOperationException("IPC not connected");
            using (var cts = new CancellationTokenSource(timeoutMs))
            {
                var result = _socket.ReceiveAsync(_buffer, cts.Token).GetAwaiter().GetResult();
                return Encoding.UTF8.GetString(_buffer.Array, 0, result.Count);
            }
        }

        public void CloseGracefully()
        {
            try
            {
                if (IsConnected)
                {
                    SendUtf8("{\"type\":\"goodbye\"}");
                    _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", CancellationToken.None)
                        .GetAwaiter().GetResult();
                }
            }
            catch { }
            Dispose();
        }

        public void Dispose()
        {
            try { if (_socket != null) _socket.Dispose(); } catch { }
            _socket = null;
        }

        private static string Escape(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }

    internal static class MarketDataTransportFactory
    {
        public static IMarketDataTransport Create(string transport, string host, int port, string pipeName, string wsUrl)
        {
            string kind = (transport ?? "tcp").Trim().ToLowerInvariant();
            if (kind == "named_pipe" || kind == "pipe")
                return new NamedPipeMarketDataTransport(pipeName);
            if (kind == "websocket" || kind == "ws")
                return new WebSocketMarketDataTransport(wsUrl);
            return new TcpMarketDataTransport(host, port);
        }
    }
}
