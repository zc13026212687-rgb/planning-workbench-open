using System.Diagnostics;
using System.Runtime.InteropServices;

namespace PlanningStudio;
internal static class ProcessOwnership
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Entry
    {
        public uint Size, Usage, Id;
        public UIntPtr Heap;
        public uint Module, Threads, Parent;
        public int BasePriority;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string File;
    }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern bool Process32FirstW(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern bool Process32NextW(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    public static bool IsDescendant(int candidate, int ancestor)
    {
        if (candidate == ancestor) return true;
        var snapshot = CreateToolhelp32Snapshot(2, 0);
        if (snapshot == new IntPtr(-1)) return false;
        try
        {
            var parents = new Dictionary<int, int>();
            var entry = new Entry { Size = (uint)Marshal.SizeOf<Entry>(), File = "" };
            if (Process32FirstW(snapshot, ref entry))
                do { parents[(int)entry.Id] = (int)entry.Parent; } while (Process32NextW(snapshot, ref entry));
            var visited = new HashSet<int>();
            while (visited.Add(candidate) && parents.TryGetValue(candidate, out candidate))
                if (candidate == ancestor) return true;
            return false;
        }
        finally { CloseHandle(snapshot); }
    }
    public static Process? CaptureOwnedProcess(int candidate, Process launcher)
    {
        try
        {
            if (!IsDescendant(candidate, launcher.Id)) return null;
            var process = Process.GetProcessById(candidate);
            // Opening a handle pins identity; later PID reuse cannot redirect cleanup.
            _ = process.Handle;
            if (process.StartTime.ToUniversalTime() < launcher.StartTime.ToUniversalTime().AddSeconds(-1)) { process.Dispose(); return null; }
            return process;
        }
        catch (Exception) { return null; }
    }
}
