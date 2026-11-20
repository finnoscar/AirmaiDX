using System;
namespace MelonLoader {
 [AttributeUsage(AttributeTargets.Assembly)]public class MelonInfoAttribute:Attribute {public MelonInfoAttribute(Type t,string n,string v,string a){}}
 public class MelonMod {public virtual void OnInitializeMelon(){}public virtual void OnUpdate(){}public virtual void OnApplicationQuit(){}}
}
namespace HarmonyLib {
 public class Harmony {public Harmony(string id){}public void Patch(System.Reflection.MethodInfo m,HarmonyMethod p){}}
 public class HarmonyMethod {public HarmonyMethod(System.Reflection.MethodInfo m){}}
}
