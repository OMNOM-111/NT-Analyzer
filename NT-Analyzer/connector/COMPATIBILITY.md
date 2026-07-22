# StratForge Connector compatibility

| Component | Supported baseline | Current evidence |
|---|---|---|
| OS | Windows 10 22H2 or Windows 11, x64 | installer/build tests on Windows; clean VM acceptance pending |
| NinjaTrader | NinjaTrader 8.1.x, 64-bit | Release compilation against the installed NinjaTrader 8 assemblies |
| Runtime | .NET Framework 4.8 | required by NinjaTrader and targeted by all Connector binaries |
| Protocol | StratForge Connector 1.0 | Python/C# signed hello and challenge interop PASS |
| Transport | outbound TLS 1.2 HTTPS to `app.stratforges.com` | local protocol harness PASS; public Production route pending |

macOS is not supported because NinjaTrader 8 is a Windows application. Windows
Server/VM use is supported only when NinjaTrader itself is installed and licensed
for that environment. The installer never installs NinjaTrader and never asks for
broker credentials.

Minor/patch Connector releases may use `safe_restart`. Major or protocol-breaking
releases require explicit approval and a compatibility gate. Live commands are
not enabled by this package.
