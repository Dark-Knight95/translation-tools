// Windows launcher with an embedded Python/Tk app payload. No installation needed.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Translation Tools")]
[assembly: AssemblyDescription("File Copier & Renamer and Subtitle Timestamp Mover")]
[assembly: AssemblyProduct("Translation Tools")]
[assembly: AssemblyVersion("2.0.2.0")]
[assembly: AssemblyFileVersion("2.0.2.0")]

internal static class Launcher
{
    private const string ResourceName = "TranslationTools.Payload.zip";

    [STAThread]
    private static int Main(string[] args)
    {
        string tempRoot = Path.GetFullPath(Path.GetTempPath());
        string workRoot = Path.Combine(tempRoot, "TranslationTools-" + Guid.NewGuid().ToString("N"));
        bool selfTest = args.Length == 2 && args[0] == "--self-test";
        string report = selfTest ? Path.GetFullPath(args[1]) : null;
        try
        {
            string extra = "";
            if (args.Length != 0)
            {
                if (selfTest)
                    extra = " --self-test " + Quote(report);
                else if (args.Length == 2 && args[0] == "--tab" &&
                         (args[1] == "renamer" || args[1] == "timestamps"))
                    extra = " --tab " + args[1];
                else
                    throw new ArgumentException("Use TranslationTools.exe, or add --tab renamer or --tab timestamps.");
            }

            Directory.CreateDirectory(workRoot);
            ExtractPayload(workRoot);
            string pythonRoot = Path.Combine(workRoot, "python");
            string appRoot = Path.Combine(workRoot, "app");
            ProcessStartInfo info = new ProcessStartInfo();
            // Self-checks use the same console-free interpreter as ordinary launches.
            info.FileName = Path.Combine(pythonRoot, "pythonw.exe");
            info.Arguments = "-I -S " + Quote(Path.Combine(appRoot, "_launch.py")) + extra;
            info.WorkingDirectory = appRoot;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            // Resolve from the fixed app working directory. This also supports redirected
            // Windows profile folders whose native and managed absolute paths differ.
            info.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine("..", "python", "tcl", "tcl8.6");
            info.EnvironmentVariables["TK_LIBRARY"] = Path.Combine("..", "python", "tcl", "tk8.6");
            // Do not let a caller's Python/Tcl configuration affect this app.
            info.EnvironmentVariables.Remove("PYTHONHOME");
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables.Remove("TCLLIBPATH");
            info.EnvironmentVariables.Remove("TKLIBPATH");
            if (selfTest)
            {
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
            }

            int exitCode;
            using (Process process = new Process())
            {
                process.StartInfo = info;
                process.Start();
                if (selfTest)
                {
                    // Drain both streams asynchronously; a test failure must not fill a pipe.
                    process.OutputDataReceived += delegate { };
                    process.ErrorDataReceived += delegate { };
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                }
                process.WaitForExit();
                exitCode = process.ExitCode;
            }
            if (exitCode != 0 && !selfTest)
            {
                string crash = Path.Combine(workRoot, "startup-error.txt");
                string message = File.Exists(crash) ? File.ReadAllText(crash) :
                    "Translation Tools could not start (code " + exitCode + "). Please try extracting the ZIP again.";
                MessageBox.Show(message, "Translation Tools", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return exitCode;
        }
        catch (Exception error)
        {
            if (selfTest)
            {
                if (report != null)
                    File.WriteAllText(report + ".launcher-error.txt", error.ToString());
            }
            else
                MessageBox.Show("Could not start Translation Tools.\n\n" + error.Message,
                    "Translation Tools", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally
        {
            // Remove only the uniquely named directory created for this launch.
            string resolved = Path.GetFullPath(workRoot);
            string parent = Path.GetFullPath(Path.GetDirectoryName(resolved));
            if (String.Equals(parent.TrimEnd(Path.DirectorySeparatorChar),
                              tempRoot.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase)
                && Path.GetFileName(resolved).StartsWith("TranslationTools-", StringComparison.Ordinal)
                && Path.GetFileName(resolved).Length == "TranslationTools-".Length + 32)
            {
                for (int attempt = 0; attempt < 3; attempt++)
                {
                    try
                    {
                        if (Directory.Exists(resolved)) Directory.Delete(resolved, true);
                        break;
                    }
                    catch (IOException) { Thread.Sleep(100); }
                    catch (UnauthorizedAccessException) { break; }
                }
            }
        }
    }

    private static void ExtractPayload(string destination)
    {
        string prefix = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(ResourceName))
        {
            if (stream == null) throw new InvalidDataException("The application payload is missing.");
            using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string target = Path.GetFullPath(Path.Combine(destination,
                        entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("The application payload contains an invalid path.");
                    if (entry.FullName.EndsWith("/", StringComparison.Ordinal))
                        Directory.CreateDirectory(target);
                    else
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        using (Stream input = entry.Open())
                        using (FileStream output = new FileStream(target, FileMode.CreateNew, FileAccess.Write))
                            input.CopyTo(output);
                    }
                }
            }
        }
    }

    private static string Quote(string value)
    {
        // Paths end in a filename, never a trailing backslash; Windows forbids quote characters.
        if (value.IndexOf('"') >= 0) throw new ArgumentException("Invalid filename.");
        return "\"" + value + "\"";
    }
}
