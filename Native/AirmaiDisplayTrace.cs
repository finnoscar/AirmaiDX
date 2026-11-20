using System;
using System.IO;
using System.Text;
using System.Reflection;
using MelonLoader;
using UnityEngine;

[assembly: MelonInfo(typeof(AirmaiDisplayTrace), "Airmai Display Trace", "0.1.0", "Airmai local diagnostics")]
// Read-only renderer observation. Never changes screen, camera or game settings.
public sealed class AirmaiDisplayTrace : MelonMod
{
    float next;
    string previous;
    static string ScreenMode()
    {
        // Unity 2017 has only fullScreen. Keep the optional 2018 API out of
        // this assembly's type/member references so the legacy CLR can load it.
        try
        {
            PropertyInfo property = typeof(Screen).GetProperty("fullScreenMode", BindingFlags.Public | BindingFlags.Static);
            if (property != null) return Convert.ToString(property.GetValue(null, null));
        }
        catch { /* Optional telemetry can fall back to the legacy property. */ }
        return Screen.fullScreen ? "Fullscreen (legacy)" : "Windowed (legacy)";
    }
    public override void OnUpdate()
    {
        if (Time.realtimeSinceStartup < next) return;
        next = Time.realtimeSinceStartup + 2f;
        try
        {
            StringBuilder s = new StringBuilder();
            s.Append("screen=").Append(Screen.width).Append("x").Append(Screen.height);
            s.Append(" display_render=").Append(Display.main.renderingWidth).Append("x").Append(Display.main.renderingHeight);
            s.Append(" display_system=").Append(Display.main.systemWidth).Append("x").Append(Display.main.systemHeight);
            s.Append(" fullscreen=").Append(Screen.fullScreen).Append(" mode=").Append(ScreenMode());
            s.Append(" target_fps=").Append(Application.targetFrameRate).Append(" vsync=").Append(QualitySettings.vSyncCount);
            s.Append(" graphics=").Append(SystemInfo.graphicsDeviceType).Append(" gpu=").Append(SystemInfo.graphicsDeviceName);
            foreach (Camera c in Camera.allCameras)
            {
                s.Append(" camera[").Append(c.name).Append("]=").Append(c.pixelWidth).Append("x").Append(c.pixelHeight);
                if (c.targetTexture != null)
                    s.Append(" texture=").Append(c.targetTexture.width).Append("x").Append(c.targetTexture.height);
            }
            string state = s.ToString();
            File.AppendAllText("C:\\AirmaiDX\\Package\\AirmaiDisplayTrace.log",
                DateTime.UtcNow.ToString("O") + " frame=" + Time.frameCount + " changed=" + (state != previous) + " " + state + "\r\n");
            previous = state;
        }
        catch { /* Renderer telemetry must not interrupt gameplay. */ }
    }
}
