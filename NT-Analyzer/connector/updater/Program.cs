using System;
using System.IO;
using System.Text;

using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace StratForge.Connector.Updater
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            try
            {
                ParsedArguments parsed = ParsedArguments.Parse(args ?? new string[0]);
                JObject result;
                if (parsed.Action == "diagnostics")
                    result = UpdaterEngine.Diagnostics(parsed.Options);
                else if (parsed.Action == "stage")
                    result = UpdaterEngine.Stage(parsed.Options);
                else if (parsed.Action == "apply-staged")
                    result = UpdaterEngine.ApplyStaged(parsed.Options);
                else if (parsed.Action == "finalize")
                    result = UpdaterEngine.FinalizePending(parsed.Options);
                else if (parsed.Action == "run")
                    result = UpdaterEngine.Run(parsed.Options);
                else
                    throw new InvalidDataException("Unknown updater action.");
                Console.WriteLine(result.ToString(Formatting.None));
                return (bool?)result["ok"] == false ? 2 : 0;
            }
            catch (UpdaterAlreadyRunningException)
            {
                Console.WriteLine(new JObject
                {
                    ["ok"] = true,
                    ["action"] = "already_running",
                    ["state"] = "single_instance_guard",
                }.ToString(Formatting.None));
                return 0;
            }
            catch (Exception exc)
            {
                Console.WriteLine(new JObject
                {
                    ["ok"] = false,
                    ["error_class"] = exc.GetType().Name,
                    ["error"] = SafeError(exc.Message),
                }.ToString(Formatting.None));
                return 2;
            }
        }

        private static string SafeError(string value)
        {
            string text = value ?? "Updater failed.";
            return text.Length <= 500 ? text : text.Substring(0, 500);
        }

        private sealed class ParsedArguments
        {
            public string Action { get; private set; } = "run";
            public UpdaterOptions Options { get; private set; } = new UpdaterOptions();

            public static ParsedArguments Parse(string[] args)
            {
                ParsedArguments parsed = new ParsedArguments();
                bool actionSeen = false;
                for (int index = 0; index < args.Length; index++)
                {
                    string arg = args[index] ?? "";
                    if (arg == "--run" || arg == "--stage" ||
                        arg == "--apply-staged" || arg == "--finalize" ||
                        arg == "--diagnostics")
                    {
                        string action = arg.Substring(2);
                        if (actionSeen && parsed.Action != action)
                            throw new InvalidDataException("Only one updater action is allowed.");
                        parsed.Action = action;
                        actionSeen = true;
                    }
                    else if (arg == "--ninja-user-dir")
                        parsed.Options.NinjaUserDir = Value(args, ref index, arg);
                    else if (arg == "--state-root")
                        parsed.Options.StateRoot = Value(args, ref index, arg);
                    else if (arg == "--package")
                        parsed.Options.PackagePath = Value(args, ref index, arg);
                    else if (arg == "--offer")
                        parsed.Options.OfferPath = Value(args, ref index, arg);
                    else if (arg == "--wait-for-safe-restart")
                        parsed.Options.WaitForSafeRestart = true;
                    else if (arg == "--approve-major")
                        parsed.Options.ApproveMajor = true;
                    else if (arg == "--non-interactive") { }
                    else
                        throw new InvalidDataException("Unknown updater argument: " + arg);
                }
                if (string.IsNullOrWhiteSpace(parsed.Options.NinjaUserDir))
                    throw new InvalidDataException("--ninja-user-dir is required.");
                if (string.IsNullOrWhiteSpace(parsed.Options.StateRoot))
                    throw new InvalidDataException("--state-root is required.");
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
