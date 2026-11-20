using System;
using System.Reflection;
using UnityEngine;
class Test {
    static string Mode() {
        return (string)typeof(AirmaiDisplayTrace).GetMethod("ScreenMode", BindingFlags.NonPublic | BindingFlags.Static).Invoke(null, null);
    }
    static void Assert(bool value) { if (!value) throw new Exception("Display mode compatibility regression"); }
    static void Main() {
#if MODERN
        Assert(Mode() == "FullScreenWindow");
        Screen.ThrowMode = true;
#endif
        Screen.fullScreen = false; Assert(Mode() == "Windowed (legacy)");
        Screen.fullScreen = true; Assert(Mode() == "Fullscreen (legacy)");
        Console.WriteLine("Display mode compatibility checks passed");
    }
}
