// A deliberately small old/new Unity API surface for compatibility regression.
using System;
namespace UnityEngine {
    public static class Screen {
        public static int width = 1080, height = 1920;
        public static bool fullScreen, ThrowMode;
#if MODERN
        public static FullScreenMode fullScreenMode {
            get { if (ThrowMode) throw new InvalidOperationException(); return FullScreenMode.FullScreenWindow; }
        }
#endif
    }
#if MODERN
    public enum FullScreenMode { FullScreenWindow }
#endif
    public static class Time { public static float realtimeSinceStartup; public static int frameCount; }
    public class Display {
        public static Display main = new Display();
        public int renderingWidth=1080, renderingHeight=1920, systemWidth=1080, systemHeight=1920;
    }
    public static class Application { public static int targetFrameRate; }
    public static class QualitySettings { public static int vSyncCount; }
    public static class SystemInfo { public static string graphicsDeviceType="test", graphicsDeviceName="test"; }
    public class RenderTexture { public int width, height; }
    public class Camera {
        public static Camera[] allCameras = new Camera[0];
        public string name; public int pixelWidth, pixelHeight; public RenderTexture targetTexture;
    }
}
