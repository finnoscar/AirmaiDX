using System;
using System.IO;
using System.Reflection;
using MelonLoader;
using HarmonyLib;
using UnityEngine;

[assembly: MelonInfo(typeof(AirmaiMouseInput), "Airmai Mouse Input", "0.1.1", "AirmaiDX")]
// Mouse input uses the game's own sensor polygons, not guessed screen regions.
// No global mouse hook, keyboard injection, card emulation or network changes.
public sealed class AirmaiMouseInput : MelonMod {
    static readonly ulong[] touches = new ulong[2];
    static readonly FieldInfo panelsField = typeof(Manager.InputManager).GetField("MouseTouchPanel", BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic);
    static readonly FieldInfo playerField = typeof(MouseTouchPanel).GetField("PlayerID", BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);
    static readonly Delegate[] touchRoots=new Delegate[2];
    static readonly MouseTouchPanel[] geometryPanels=new MouseTouchPanel[2];
    static readonly MeshButton[][] geometryButtons=new MeshButton[2][];
    static Delegate buttonsRoot, auxRoot;
    static int sampledFrame = -1, startUntil = -1, serviceUntil = -1;
    static bool enabled, failed, suspended, releaseRequired = true, wasFocused = true;
    static Func<bool> hdxReady, controllerReady;
    static string mode = "mouse";
    static float nextStatus;
    static float nextRegister;
    static string language = "en";
    static GUIStyle toolbarStyle;
    static bool localizedToolbar;
    static void Log(string message) {
        try { File.AppendAllText("C:\\AirmaiDX\\Package\\AirmaiMouseInput.log", DateTime.UtcNow.ToString("O")+" "+message+"\r\n"); } catch {}
    }
    public override void OnInitializeMelon() {
        try {
            string[] config = File.ReadAllLines("C:\\AirmaiMouse.cfg");
            if(config.Length!=2 || config[0]!="AIRMAI_MOUSE_V1" || panelsField==null || playerField==null) throw new InvalidDataException();
            language=config[1];
            var harmony = new HarmonyLib.Harmony("airmai.mouse.input");
            MethodInfo raycast=typeof(MeshButton).GetMethod("IsRaycastLocationValid");
            if(raycast==null) throw new MissingMethodException();
            MethodInfo dummyTouch=typeof(MouseTouchPanel).GetProperty("GetPushFlag")?.GetGetMethod();
            if(dummyTouch==null) throw new MissingMethodException();
            harmony.Patch(dummyTouch, postfix: new HarmonyMethod(typeof(AirmaiMouseInput).GetMethod("AfterDummyTouch")));
            harmony.Patch(raycast, new HarmonyMethod(typeof(AirmaiMouseInput).GetMethod("BeforeStockMouse")));
            enabled=true;Log("Enabled live-projected mouse geometry v0.1.1; waiting for outer-button provider.");
        } catch(Exception error) { Log("Mouse input unavailable: "+error.GetType().Name); }
    }
    // AirmaiDisplayBridge presents a portrait texture with proportional black
    // bars. Convert the pointer back into that exact texture's pixel space.
    public static bool MapPoint(float x,float y,float outputW,float outputH,float renderW,float renderH,out Vector2 result) {
        result=Vector2.zero;
        if(outputW<=0 || outputH<=0 || renderW<=0 || renderH<=0 || float.IsNaN(x) || float.IsNaN(y)) return false;
        float scale=Math.Min(outputW/renderW,outputH/renderH);
        float left=(outputW-renderW*scale)/2, bottom=(outputH-renderH*scale)/2;
        if(x<left || x>=outputW-left || y<bottom || y>=outputH-bottom) return false;
        result=new Vector2((x-left)/scale,(y-bottom)/scale);return true;
    }
    static Rect Toolbar { get { return new Rect(12,Screen.height-44,216,32); } }
    // Project the original sensor vertices through the CURRENT camera. The
    // game's IsInside uses vertices cached in Awake; AquaMai also rewrites
    // those vertices into panel-local coordinates. Neither cache is a stable
    // screen-space contract after a render target or display change.
    static bool Contains(MeshButton button,Camera camera,Vector2 point) {
        CustomGraphic graphic=button.targetGraphic as CustomGraphic;
        if(graphic==null || graphic.vertex==null || graphic.vertex.Count<3) return false;
        bool inside=false;
        Vector2 v=graphic.vertex[graphic.vertex.Count-1];
        Vector3 previous=camera.WorldToScreenPoint(graphic.transform.TransformPoint(new Vector3(v.x,v.y,0)));
        for(int i=0;i<graphic.vertex.Count;i++) {
            v=graphic.vertex[i];
            Vector3 current=camera.WorldToScreenPoint(graphic.transform.TransformPoint(new Vector3(v.x,v.y,0)));
            if((current.y>point.y)!=(previous.y>point.y) &&
                point.x<(previous.x-current.x)*(point.y-current.y)/(previous.y-current.y)+current.x) inside=!inside;
            previous=current;
        }
        return inside;
    }
    static void Sample() {
        RefreshMode();
        if(sampledFrame==Time.frameCount) return;sampledFrame=Time.frameCount;
        Array.Clear(touches,0,2);
        if(!MouseActive || !(Input.GetMouseButton(0)||Input.GetMouseButtonDown(0))) return;
        Vector3 mouse=Input.mousePosition;
        if(Toolbar.Contains(new Vector2(mouse.x,Screen.height-mouse.y))) return;
        Camera camera=Camera.main;if(camera==null) return;
        Vector2 point=new Vector2(mouse.x,mouse.y);
        if(camera.targetTexture!=null && camera.targetTexture.name=="Airmai scene render") {
            if(!MapPoint(mouse.x,mouse.y,Screen.width,Screen.height,camera.targetTexture.width,camera.targetTexture.height,out point)) return;
        } else if(mouse.x<0 || mouse.y<0 || mouse.x>=Screen.width || mouse.y>=Screen.height) return;
        var panels=panelsField.GetValue(null) as MouseTouchPanel[];if(panels==null) return;
        for(int player=0;player<Math.Min(2,panels.Length);player++) {
            MouseTouchPanel panel=panels[player];if(panel==null) continue;
            if(geometryPanels[player]!=panel) {
                geometryPanels[player]=panel;
                geometryButtons[player]=panel.GetComponentsInChildren<MeshButton>(true);
            }
            foreach(MeshButton button in geometryButtons[player]) {
                if(button==null) continue;
                int index=(int)button.GetTouchPanelArea;
                if(index>=0 && index<34 && Contains(button,camera,point)) touches[player]|=1UL<<index;
            }
        }
    }
    static bool MouseActive { get { return enabled && !suspended && !releaseRequired && Application.isFocused; } }
    static Func<bool> Readiness(Assembly assembly,string typeName) {
        Type type=assembly.GetType(typeName);
        MethodInfo method=type==null?null:type.GetMethod("HasLiveInput",BindingFlags.Static|BindingFlags.Public);
        return method==null?null:(Func<bool>)Delegate.CreateDelegate(typeof(Func<bool>),method);
    }
    static void Release() {
        Array.Clear(touches,0,2);startUntil=serviceUntil=-1;sampledFrame=-1;
        // A held pointer must not turn into a new press after reconnect/focus.
        releaseRequired=true;
    }
    static void RefreshMode() {
        string next=hdxReady!=null && hdxReady()?"hdx":controllerReady!=null && controllerReady()?"adx":"mouse";
        bool nextSuspended=next!="mouse";
        if(nextSuspended!=suspended || (wasFocused && !Application.isFocused)) Release();
        suspended=nextSuspended;wasFocused=Application.isFocused;
        if(releaseRequired && !Input.GetMouseButton(0) && !Input.GetMouseButtonDown(0) && !Input.GetMouseButton(1)) releaseRequired=false;
        if(next!=mode) { mode=next;nextStatus=0;Log("Input mode="+mode+"; mouse buttons, touch and toolbar "+(suspended?"suspended":"resumed")); }
    }
    static void WriteStatus() {
        if(Time.realtimeSinceStartup<nextStatus)return;nextStatus=Time.realtimeSinceStartup+1;
        try { File.WriteAllText("C:\\AirmaiMouse-state.txt","AIRMAI_MOUSE_STATE_V1\n"+(enabled?mode:"keyboard")+"\n"); } catch {}
    }
    public static bool BeforeStockMouse(ref bool __result) {
        if(!enabled) return true;__result=false;return false;
    }
    // With DummyTouchPanel=1, InputManager reads this getter instead of the
    // IO.NewTouchPanel.Execute path patched by AquaMai's TouchStatusProvider.
    // Preserve existing input and use the same gated sample as the real path.
    public static void AfterDummyTouch(MouseTouchPanel __instance,ref ulong __result) {
        try { __result|=ReadTouch((int)playerField.GetValue(__instance)); }
        catch(Exception error) { Disable(error); }
    }
    public static ulong ReadTouch(int player) {
        try {
            Sample();return MouseActive && player>=0 && player<2 ? touches[player] : 0UL;
        } catch(Exception error) { Disable(error);return 0UL; }
    }
    public static bool ReadButton(int player,int button) {
        try { Sample();return MouseActive && player>=0 && player<2 && button>=1 && button<=8 && (touches[player]&(1UL<<(button-1)))!=0; }
        catch(Exception error) { Disable(error);return false; }
    }
    public static T ReadAux<T>() {
        try { Sample(); } catch(Exception error) { Disable(error); }
        object value=Activator.CreateInstance(typeof(T));
        if(MouseActive) {
            SetAux(value,"select1P",Time.frameCount<=startUntil || Input.GetMouseButton(1));
            SetAux(value,"service",Time.frameCount<=serviceUntil);
        }
        return (T)value;
    }
    static void SetAux(object value,string name,bool state) {
        FieldInfo field=value.GetType().GetField(name);if(field!=null && field.FieldType==typeof(bool)) field.SetValue(value,state);
    }
    static void Disable(Exception error) {
        enabled=false;Release();nextStatus=0;WriteStatus();
        if(!failed) { failed=true;Log("Mouse disabled; keyboard remains available: "+error.GetType().Name); }
    }
    public override void OnUpdate() {
        if(!enabled) return;
        try {
            Sample();
            WriteStatus();
            if(Time.realtimeSinceStartup<nextRegister) return;
            nextRegister=Time.realtimeSinceStartup+1;
            foreach(Assembly assembly in AppDomain.CurrentDomain.GetAssemblies()) {
                if(hdxReady==null) hdxReady=Readiness(assembly,"AirmaiHdxNativeTouch");
                if(controllerReady==null) controllerReady=Readiness(assembly,"AirmaiControllerInput");
                MethodInfo touch=assembly.GetType("AquaMai.Core.Helpers.TouchStatusProvider")?.GetMethod("RegisterTouchStatusProvider",BindingFlags.Static|BindingFlags.Public);
                if(touch!=null && touch.GetParameters().Length==2) for(int player=0;player<2;player++) if(touchRoots[player]==null) {
                    Type callback=touch.GetParameters()[1].ParameterType;
                    Delegate candidate=Delegate.CreateDelegate(callback,typeof(AirmaiMouseInput).GetMethod("ReadTouch"));
                    touch.Invoke(null,new object[]{player,candidate});touchRoots[player]=candidate;Log("Registered mouse touch for player "+(player+1)+" through AquaMai TouchStatusProvider.");
                }
                Type hook=assembly.GetType("AquaMai.Core.Helpers.JvsSwitchHook");if(hook==null) continue;
                MethodInfo button=hook.GetMethod("RegisterButtonChecker",BindingFlags.Static|BindingFlags.Public);
                if(buttonsRoot==null && button!=null) {
                    buttonsRoot=Delegate.CreateDelegate(button.GetParameters()[0].ParameterType,typeof(AirmaiMouseInput).GetMethod("ReadButton"));
                    button.Invoke(null,new object[]{buttonsRoot});Log("Registered mouse outer buttons.");
                }
                MethodInfo aux=hook.GetMethod("RegisterAuxiliaryStateProvider",BindingFlags.Static|BindingFlags.Public);
                if(auxRoot==null && aux!=null) {
                    Type type=aux.GetParameters()[0].ParameterType;
                    auxRoot=Delegate.CreateDelegate(type,typeof(AirmaiMouseInput).GetMethod("ReadAux").MakeGenericMethod(type.GetMethod("Invoke").ReturnType));
                    aux.Invoke(null,new object[]{auxRoot});Log("Registered mouse start and service buttons.");
                }
            }
        } catch(Exception error) { Disable(error); }
    }
    public override void OnGUI() {
        if(!enabled) return;
        try { Sample(); } catch(Exception error) { Disable(error);return; }
        if(!MouseActive) return;
        Rect r=Toolbar;
        if(toolbarStyle==null) {
            // Game GUI skins may have a missing font or white-on-white text.
            // Own only this style; never modify the game's global GUI skin.
            toolbarStyle=new GUIStyle(GUI.skin.button);toolbarStyle.fontSize=14;toolbarStyle.alignment=TextAnchor.MiddleCenter;
            string required=language=="ja"?"スタートサービス":language=="zh-Hans"?"开始选择服务投币":"Start / SelectService credit";
            foreach(Font font in Resources.FindObjectsOfTypeAll<Font>()) {
                bool supported=true;foreach(char character in required)if(character!=' ' && character!='/' && !font.HasCharacter(character)){supported=false;break;}
                if(supported) {toolbarStyle.font=font;localizedToolbar=true;break;}
            }
            if(!localizedToolbar) toolbarStyle.font=Font.CreateDynamicFontFromOSFont("Arial",14);
            toolbarStyle.normal.textColor=toolbarStyle.hover.textColor=toolbarStyle.active.textColor=Color.black;
        }
        string start=localizedToolbar&&language=="ja"?"スタート":localizedToolbar&&language=="zh-Hans"?"开始 / 选择":"Start / Select";
        string service=localizedToolbar&&language=="ja"?"サービス":localizedToolbar&&language=="zh-Hans"?"服务投币":"Service credit";
        Color previous=GUI.contentColor;
        try {
            GUI.contentColor=Color.white;
            if(GUI.Button(new Rect(r.x,r.y,104,r.height),start,toolbarStyle)) startUntil=Time.frameCount+3;
            if(GUI.Button(new Rect(r.x+112,r.y,104,r.height),service,toolbarStyle)) serviceUntil=Time.frameCount+3;
        } finally {GUI.contentColor=previous;}
    }
    public override void OnApplicationQuit() { enabled=false;Release();nextStatus=0;WriteStatus(); }
}
