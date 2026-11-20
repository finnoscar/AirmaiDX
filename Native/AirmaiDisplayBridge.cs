using System;
using System.IO;
using MelonLoader;
using UnityEngine;

[assembly: MelonInfo(typeof(AirmaiDisplayBridge), "Airmai Display Bridge", "0.1.0", "AirmaiDX")]
// The game window fills the chosen display. Only the game camera renders into
// an optional smaller texture; a separate camera presents it to the full window.
public sealed class AirmaiDisplayBridge : MelonMod {
    static RenderTexture scene;
    static Camera original,presenter;
    static RenderTexture previous;
    static int requestedW,requestedH;
    float next;
    static void Log(string value) {
        try { File.AppendAllText("C:\\AirmaiDX\\Package\\AirmaiDisplayBridge.log",DateTime.UtcNow.ToString("O")+" "+value+"\r\n"); } catch {}
    }
    public override void OnUpdate() {
        if(Time.realtimeSinceStartup<next)return;next=Time.realtimeSinceStartup+2f;
        try {
            string[] lines=File.ReadAllLines("C:\\AirmaiDisplay.cfg");
            int w,h;
            if(lines.Length!=3||lines[0]!="AIRMAI_DISPLAY_V1"||!int.TryParse(lines[1],out w)||!int.TryParse(lines[2],out h)||
                w<360||w>4320||h<640||h>7680||Math.Abs((double)w/h-9.0/16)>.001)return;
            Camera camera=Camera.main;
            if(camera==null||camera==presenter)return;
            bool bypass=Screen.width==w&&Screen.height==h;
            if(bypass) { if(scene!=null)Restore();return; }
            if(original!=camera||requestedW!=w||requestedH!=h||scene==null) {
                Restore();original=camera;previous=camera.targetTexture;
                if(previous!=null) { Log("Existing game camera target left unchanged");original=null;return; }
                scene=new RenderTexture(w,h,24,RenderTextureFormat.ARGB32);scene.name="Airmai scene render";scene.filterMode=FilterMode.Bilinear;
                if(!scene.Create()) { Log("Render texture creation failed");Restore();return; }
                original.targetTexture=scene;requestedW=w;requestedH=h;
                GameObject go=new GameObject("Airmai Presentation");UnityEngine.Object.DontDestroyOnLoad(go);
                presenter=go.AddComponent<Camera>();presenter.cullingMask=0;presenter.clearFlags=CameraClearFlags.Nothing;
                presenter.allowHDR=false;presenter.allowMSAA=false;presenter.useOcclusionCulling=false;
                presenter.depthTextureMode=DepthTextureMode.None;presenter.renderingPath=RenderingPath.Forward;
                presenter.depth=original.depth+100;presenter.orthographic=true;presenter.rect=new Rect(0,0,1,1);
                go.AddComponent<AirmaiPresentation>();
                Log("scene="+w+"x"+h+" output="+Screen.width+"x"+Screen.height);
            }
        } catch(Exception e) { Log("Display setup "+e.GetType().Name);Restore(); }
    }
    static void Restore() {
        if(original!=null)original.targetTexture=previous;
        if(presenter!=null)UnityEngine.Object.Destroy(presenter.gameObject);
        if(scene!=null){scene.Release();UnityEngine.Object.Destroy(scene);}
        scene=null;presenter=null;original=null;previous=null;
    }
    public override void OnApplicationQuit(){Restore();}
    public sealed class AirmaiPresentation : MonoBehaviour {
        void OnRenderImage(RenderTexture source,RenderTexture destination) {
            // Unity 2018 redirects a null Blit destination to Camera.main's
            // target texture. Temporarily clear it so presentation reaches the
            // screen, then restore the original camera before the next frame.
            Camera main=Camera.main;
            RenderTexture saved=main==null?null:main.targetTexture;
            if(destination==null&&main!=null)main.targetTexture=null;
            try {
                RenderTexture image=scene!=null?scene:source;
                float width=destination!=null?destination.width:Screen.width;
                float height=destination!=null?destination.height:Screen.height;
                if(image==null||Math.Abs(width/height-(float)image.width/image.height)<.001f) {
                    Graphics.Blit(image,destination);
                } else {
                    // Preserve the portrait game's proportions on a landscape
                    // Mac display; clear unused sides instead of stretching it.
                    RenderTexture active=RenderTexture.active;
                    RenderTexture.active=destination;GL.PushMatrix();
                    try {
                        GL.Clear(true,true,Color.black);GL.LoadPixelMatrix(0,width,height,0);
                        float scale=Math.Min(width/image.width,height/image.height);
                        float w=image.width*scale,h=image.height*scale;
                        Graphics.DrawTexture(new Rect((width-w)/2,(height-h)/2,w,h),image);
                    } finally { GL.PopMatrix();RenderTexture.active=active; }
                }
            }
            finally { if(destination==null&&main!=null)main.targetTexture=saved; }
        }
    }
}
