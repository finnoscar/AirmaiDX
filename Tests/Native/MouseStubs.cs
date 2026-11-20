using System;
namespace MelonLoader {
 [AttributeUsage(AttributeTargets.Assembly,AllowMultiple=true)] public class MelonInfoAttribute:Attribute {public MelonInfoAttribute(Type t,string n,string v,string a){}}
 public class MelonMod {public virtual void OnInitializeMelon(){}public virtual void OnUpdate(){}public virtual void OnGUI(){}public virtual void OnApplicationQuit(){}}
}
namespace HarmonyLib {
 public class Harmony {public Harmony(string id){}public void Patch(System.Reflection.MethodInfo m,HarmonyMethod prefix=null,HarmonyMethod postfix=null){}}
 public class HarmonyMethod {public HarmonyMethod(System.Reflection.MethodInfo m){}}
}
namespace UnityEngine {
 public struct Vector2 {public float x,y;public Vector2(float a,float b){x=a;y=b;}public static Vector2 zero {get{return new Vector2();}}}
 public struct Vector3 {public float x,y,z;public Vector3(float a,float b,float c){x=a;y=b;z=c;}}
 public class RenderTexture {public string name;public int width,height;}
 public class Camera {public static Camera main;public RenderTexture targetTexture;public Vector3 WorldToScreenPoint(Vector3 p){float scale=targetTexture==null?1:targetTexture.width/1080f;return new Vector3(p.x*scale,p.y*scale,p.z);}}
 public class Transform {public Vector3 offset;public Vector3 TransformPoint(Vector3 p){return new Vector3(p.x+offset.x,p.y+offset.y,p.z+offset.z);}}
 public static class Screen {public static int width=2560,height=1440;}
 public static class Application {public static bool isFocused=true;}
 public static class Time {public static int frameCount;public static float realtimeSinceStartup;}
 public static class Input {public static bool held,down,right;public static Vector3 mousePosition;public static bool GetMouseButton(int index){return index==0?held:right;}public static bool GetMouseButtonDown(int index){return down;}}
 public struct Rect {public float x,y,width,height;public Rect(float a,float b,float c,float d){x=a;y=b;width=c;height=d;}public bool Contains(Vector2 p){return p.x>=x&&p.y>=y&&p.x<x+width&&p.y<y+height;}}
 public struct Color {public static Color black,white;}
 public enum TextAnchor {MiddleCenter}
 public class Font {public bool HasCharacter(char c){return true;}public static Font CreateDynamicFontFromOSFont(string name,int size){return new Font();}}
 public static class Resources {public static T[] FindObjectsOfTypeAll<T>(){return new T[0];}}
 public class GUIStyleState {public Color textColor;}
 public class GUIStyle {public GUIStyle(GUIStyle other){}public GUIStyle(){}public int fontSize;public TextAnchor alignment;public Font font;public GUIStyleState normal=new GUIStyleState(),hover=new GUIStyleState(),active=new GUIStyleState();}
 public class GUISkin {public GUIStyle button=new GUIStyle();}
 public static class GUI {public static GUISkin skin=new GUISkin();public static Color contentColor;public static int calls;public static bool click;public static bool Button(Rect r,string s,GUIStyle style){calls++;return click;}}
}
namespace Manager {public static class InputManager {
 public enum TouchPanelArea {A1=0,A4=3,C1=16,Blank=34,End=35}
 public static MouseTouchPanel[] MouseTouchPanel=new MouseTouchPanel[2];
}}
public class MouseTouchPanel {
 public int PlayerID;public ulong GetPushFlag {get{return 0;}}
 public MeshButton[] sensors=new MeshButton[0];
 public T[] GetComponentsInChildren<T>(bool inactive){return (T[])(object)sensors;}
}
public class CustomGraphic {public System.Collections.Generic.List<UnityEngine.Vector2> vertex=new System.Collections.Generic.List<UnityEngine.Vector2>();public UnityEngine.Transform transform=new UnityEngine.Transform();}
public class MeshButton {public Manager.InputManager.TouchPanelArea GetTouchPanelArea;public CustomGraphic targetGraphic;public bool IsRaycastLocationValid(){return true;}}
namespace AquaMai.Core.Helpers {public static class JvsSwitchHook {
 public delegate bool Buttons(int p,int b);public delegate AuxiliaryState Aux();
 public struct AuxiliaryState {public bool select1P,select2P,service,test;}
 // The shipped AquaMai APIs append providers and OR their results. Using a
 // single replaceable delegate hides collisions between mouse and hardware.
 public static readonly System.Collections.Generic.List<Buttons> buttonProviders=new System.Collections.Generic.List<Buttons>();
 public static readonly System.Collections.Generic.List<Aux> auxProviders=new System.Collections.Generic.List<Aux>();
 public static Buttons buttons=ReadButtons;public static Aux aux=ReadAux;
 static bool ReadButtons(int p,int b){foreach(var provider in buttonProviders)if(provider(p,b))return true;return false;}
 static AuxiliaryState ReadAux(){var result=new AuxiliaryState();foreach(var provider in auxProviders){var a=provider();result.select1P|=a.select1P;result.select2P|=a.select2P;result.service|=a.service;result.test|=a.test;}return result;}
 public static void RegisterButtonChecker(Buttons value){buttonProviders.Add(value);}
 public static void RegisterAuxiliaryStateProvider(Aux value){auxProviders.Add(value);}
}}
namespace AquaMai.Core.Helpers {public static class TouchStatusProvider {
 public delegate ulong Touch(int player);
 public static readonly System.Collections.Generic.List<Touch>[] registered={new System.Collections.Generic.List<Touch>(),new System.Collections.Generic.List<Touch>()};
 public static Touch[] providers={Read,Read};
 static ulong Read(int player){ulong value=0;foreach(var provider in registered[player])value|=provider(player);return value;}
 public static void RegisterTouchStatusProvider(int player,Touch value){registered[player].Add(value);}
}}
