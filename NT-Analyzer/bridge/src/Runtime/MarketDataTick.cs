using System;
using System.Globalization;

namespace NTAnalyzerBridge.Runtime
{
    /// <summary>
    /// Minimal market-data tick for the Bridge→backend IPC path.
    /// Built in the MarketData callback without file I/O or bar aggregation.
    /// </summary>
    internal struct MarketDataTick
    {
        public string EventType;
        public string Instrument;
        public string SubscriptionId;
        public double Price;
        public double Bid;
        public double Ask;
        public long Volume;
        public DateTime TsEventUtc;
        public DateTime TsEnqueuedUtc;
        public long GeneratedSequence;
        public long? ExchangeSequence;
        public long? ProviderSequence;

        public string ToJsonObject(string connectionId, long connectionSequence, int sourceEpoch)
        {
            // Keep payload compact; writer thread owns serialization.
            string exchange = ExchangeSequence.HasValue
                ? ExchangeSequence.Value.ToString(CultureInfo.InvariantCulture)
                : "null";
            string providerSeq = ProviderSequence.HasValue
                ? ProviderSequence.Value.ToString(CultureInfo.InvariantCulture)
                : "null";
            return "{"
                + "\"type\":\"event\","
                + "\"event\":{"
                + "\"type\":\"" + JsonEscape(EventType) + "\","
                + "\"provider\":\"ninjatrader\","
                + "\"raw_symbol\":\"" + JsonEscape(Instrument) + "\","
                + "\"exact_contract\":\"" + JsonEscape(Instrument) + "\","
                + "\"subscription_id\":\"" + JsonEscape(SubscriptionId) + "\","
                + "\"channel\":\"trades\","
                + "\"data_plane\":\"display\","
                + "\"price\":" + Price.ToString(CultureInfo.InvariantCulture) + ","
                + "\"bid\":" + Bid.ToString(CultureInfo.InvariantCulture) + ","
                + "\"ask\":" + Ask.ToString(CultureInfo.InvariantCulture) + ","
                + "\"volume\":" + Volume.ToString(CultureInfo.InvariantCulture) + ","
                + "\"exchange_sequence\":" + exchange + ","
                + "\"provider_sequence\":" + providerSeq + ","
                + "\"connection_sequence\":" + connectionSequence.ToString(CultureInfo.InvariantCulture) + ","
                + "\"generated_sequence\":" + GeneratedSequence.ToString(CultureInfo.InvariantCulture) + ","
                + "\"source_epoch\":" + sourceEpoch.ToString(CultureInfo.InvariantCulture) + ","
                + "\"ts_event\":\"" + TsEventUtc.ToString("o", CultureInfo.InvariantCulture) + "\","
                + "\"ts_provider\":\"" + TsEnqueuedUtc.ToString("o", CultureInfo.InvariantCulture) + "\","
                + "\"connection_id\":\"" + JsonEscape(connectionId) + "\","
                + "\"quality\":{\"bridge_tick\":true}"
                + "}}";
        }

        private static string JsonEscape(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
