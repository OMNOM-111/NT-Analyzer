using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace StratForge.Connector.Setup
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            try
            {
                string releaseRoot = Path.GetDirectoryName(
                    typeof(Program).Assembly.Location) ?? Environment.CurrentDirectory;
                VerifiedRelease release = ReleaseManifestVerifier.Verify(releaseRoot);
                ParsedArguments parsed = ParsedArguments.Parse(args ?? new string[0]);
                if (parsed.PairingUri != "")
                    parsed.Options.EnrollmentCode = EnrollmentFromUri(parsed.PairingUri);
                if (parsed.Action == "verify")
                {
                    WriteJson(new JObject
                    {
                        ["ok"] = true,
                        ["action"] = "verify",
                        ["version"] = release.Version,
                        ["channel"] = release.Channel,
                        ["trust_tier"] = release.TrustTier,
                        ["manifest_sha256"] = release.ManifestSha256,
                    });
                    return 0;
                }
                if (parsed.Action == "detect")
                {
                    WriteJson(new JObject
                    {
                        ["ok"] = true,
                        ["action"] = "detect",
                        ["ninja_user_dirs"] = new JArray(InstallerEngine.DetectNinjaUserDirs()),
                    });
                    return 0;
                }
                if (parsed.Action == "")
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    using (SetupWizard wizard = new SetupWizard(release, parsed.Options))
                        Application.Run(wizard);
                    return 0;
                }
                EnsureNinjaDir(parsed.Options);
                JObject result;
                if (parsed.Action == "install")
                    result = InstallerEngine.InstallOrRepair(release, parsed.Options, false);
                else if (parsed.Action == "repair")
                    result = InstallerEngine.InstallOrRepair(release, parsed.Options, true);
                else if (parsed.Action == "uninstall")
                    result = InstallerEngine.Uninstall(release, parsed.Options);
                else if (parsed.Action == "diagnostics")
                    result = InstallerEngine.Diagnostics(release, parsed.Options);
                else
                    throw new InvalidDataException("Unknown installer action.");
                WriteJson(result);
                return 0;
            }
            catch (Exception exc)
            {
                WriteJson(new JObject
                {
                    ["ok"] = false,
                    ["error_class"] = exc.GetType().Name,
                    ["error"] = SafeError(exc.Message),
                });
                return 2;
            }
        }

        private static void EnsureNinjaDir(InstallOptions options)
        {
            if (!string.IsNullOrWhiteSpace(options.NinjaUserDir)) return;
            IList<string> found = InstallerEngine.DetectNinjaUserDirs();
            if (found.Count == 1) options.NinjaUserDir = found[0];
            else throw new InvalidOperationException(
                found.Count == 0
                    ? "NinjaTrader user directory was not detected; provide --ninja-user-dir."
                    : "Multiple NinjaTrader user directories were detected; select one explicitly.");
        }

        private static string EnrollmentFromUri(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri) ||
                !string.Equals(uri.Scheme, "stratforge-connector", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Pairing URI scheme is invalid.");
            foreach (string pair in uri.Query.TrimStart('?').Split('&'))
            {
                string[] values = pair.Split(new[] { '=' }, 2);
                if (values.Length == 2 && values[0] == "code")
                    return Uri.UnescapeDataString(values[1]);
            }
            throw new InvalidDataException("Pairing URI does not contain an enrollment code.");
        }

        private static string SafeError(string value)
        {
            string text = value ?? "Installer failed.";
            return text.Length <= 500 ? text : text.Substring(0, 500);
        }

        private static void WriteJson(JObject value)
        {
            Console.WriteLine((value ?? new JObject()).ToString(Formatting.None));
        }

        private sealed class ParsedArguments
        {
            public string Action { get; private set; } = "";
            public string PairingUri { get; private set; } = "";
            public InstallOptions Options { get; private set; } = new InstallOptions();

            public static ParsedArguments Parse(string[] args)
            {
                ParsedArguments parsed = new ParsedArguments();
                for (int index = 0; index < args.Length; index++)
                {
                    string arg = args[index] ?? "";
                    if (arg == "--verify" || arg == "--detect" || arg == "--install" ||
                        arg == "--repair" || arg == "--uninstall" || arg == "--diagnostics")
                    {
                        string action = arg.Substring(2);
                        if (parsed.Action != "" && parsed.Action != action)
                            throw new InvalidDataException("Only one installer action is allowed.");
                        parsed.Action = action;
                    }
                    else if (arg == "--ninja-user-dir") parsed.Options.NinjaUserDir = Value(args, ref index, arg);
                    else if (arg == "--server-origin")
                    {
                        parsed.Options.ServerOrigin = Value(args, ref index, arg);
                        parsed.Options.ServerOriginExplicit = true;
                    }
                    else if (arg == "--enrollment-code") parsed.Options.EnrollmentCode = Value(args, ref index, arg);
                    else if (arg == "--channel") parsed.Options.Channel = Value(args, ref index, arg);
                    else if (arg == "--update-policy") parsed.Options.UpdatePolicy = Value(args, ref index, arg);
                    else if (arg == "--state-root") parsed.Options.StateRoot = Value(args, ref index, arg);
                    else if (arg == "--pairing-uri") parsed.PairingUri = Value(args, ref index, arg);
                    else if (arg == "--migrate-local") parsed.Options.MigrateLocal = true;
                    else if (arg == "--allow-local-backend")
                        parsed.Options.AllowLocalBackend = true;
                    else if (arg == "--runtime-data-dir")
                        parsed.Options.RuntimeDataDir = Value(args, ref index, arg);
                    else if (arg == "--skip-uri-registration") parsed.Options.SkipUriRegistration = true;
                    else if (arg == "--non-interactive") { }
                    else throw new InvalidDataException("Unknown installer argument: " + arg);
                }
                return parsed;
            }

            private static string Value(string[] args, ref int index, string name)
            {
                if (++index >= args.Length || string.IsNullOrWhiteSpace(args[index]))
                    throw new InvalidDataException(name + " requires a value.");
                return args[index];
            }
        }
    }
}
