using System;
using System.IO;
using System.Reflection;
using System.Collections;
using MelonLoader;
using HarmonyLib;
using UnityEngine;

[assembly: MelonInfo(typeof(AirmaiBootTrace), "Airmai Boot Trace", "0.1.0", "Airmai local diagnostics")]
// Observation only: every original method executes normally; no flags or results are changed.
public sealed class AirmaiBootTrace : MelonMod
{
    static readonly object Gate = new object();
    static string previous;
    static Type manager;
    static int frames;
    static object gameObject;
    static bool backupRecorded;
    static readonly string[] Flags = { "IsException", "IsGotoSystemTest", "IsGotoReboot", "IsGotoSystemError" };
    static void Write(string message)
    {
        try { lock (Gate) File.AppendAllText("C:\\AirmaiDX\\Package\\AirmaiBootTrace.log", DateTime.UtcNow.ToString("O") + " " + message + "\r\n"); }
        catch { /* Diagnostic failure must not affect the game. */ }
    }
    public override void OnInitializeMelon()
    {
        Write("initialized; observation-only");
        Application.logMessageReceived += OnUnityLog;
        foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (a.GetName().Name != "Assembly-CSharp") continue;
            manager = a.GetType("Manager.GameManager");
            Type main = a.GetType("Main.GameMainObject");
            MethodInfo update = main == null ? null : main.GetMethod("Update", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (update == null) { Write("Update method unavailable"); continue; }
            try
            {
                var h = new HarmonyLib.Harmony("airmai.local.observation");
                h.Patch(update, new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("BeforeUpdate")), new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("AfterUpdate")));
                Write("Update observation installed");
                Type cfg = a.GetType("MAI2System.Config");
                MethodInfo init = cfg == null ? null : cfg.GetMethod("initialize", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                if (init != null) h.Patch(init, null, new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("AfterConfig")));
                Type backupType = a.GetType("Manager.Backup");
                MethodInfo backupReady = backupType == null ? null : backupType.GetMethod("Execute_Ready", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
                if (backupReady != null) h.Patch(backupReady, null, new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("AfterBackupReady")));
                string[] stages = {
                    "Main.GameMainObject|Awake", "Main.GameMainObject|Start", "Main.GameMainObject|InitializeCriGameObject",
                    "Manager.WasapiExclusive|Intialize", "CommonPrefab|CreatePrefab", "CommonScriptable|CreateScriptable",
                    "ButtonControllerBase|LoadDefaultResources", "Manager.GameManager|Initialize",
                    "Manager.DLMusicScoreManager|Initialize", "Manager.NetDataManager|Initialize", "Manager.SeManager|Initialize"
                };
                foreach (string stage in stages)
                {
                    string[] parts = stage.Split('|');
                    Type stageType = a.GetType(parts[0]);
                    if (stageType == null) continue;
                    foreach (MethodInfo method in stageType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
                        if (method.Name == parts[1] && method.DeclaringType == stageType)
                            h.Patch(method, new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("BeforeStage")), new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("AfterStage")));
                }
                Type input = a.GetType("Manager.InputManager");
                if (input != null)
                    foreach (MethodInfo method in input.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
                        if ((method.Name == "GetButtonDown" || method.Name == "GetSystemInputDown") && method.ReturnType == typeof(bool))
                            h.Patch(method, null, new HarmonyMethod(typeof(AirmaiBootTrace).GetMethod("AfterInputRead")));
            }
            catch (Exception e) { Write("observation setup error: " + e); }
        }
    }
    static void OnUnityLog(string message, string stack, LogType type)
    {
        if (type == LogType.Exception || type == LogType.Error || type == LogType.Assert)
            Write("Unity " + type + ": " + message + "\n" + stack);
    }
    public static void BeforeUpdate(object __instance) { gameObject = __instance; Snapshot("before"); }
    public static void AfterUpdate() {
        Snapshot("after");
        foreach (KeyCode key in new[] { KeyCode.W, KeyCode.E, KeyCode.D, KeyCode.C, KeyCode.X, KeyCode.Z, KeyCode.A, KeyCode.Q, KeyCode.Return, KeyCode.Alpha5, KeyCode.F1, KeyCode.F2 })
            if (Input.GetKeyDown(key)) Write("raw keyboard down " + key);
        if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.Alpha3)) KeyboardPath();
    }
    public static void AfterInputRead(MethodBase __originalMethod, object[] __args, bool __result)
    {
        if (!__result) return;
        string values = "";
        foreach (object value in __args) values += Convert.ToString(value) + " ";
        Write("game input down " + __originalMethod.Name + " " + values);
    }
    public static void AfterConfig(object __instance)
    {
        try {
            string values = "";
            foreach (string name in new[] { "IsTarget", "IsIgnoreError", "IsDummyTouchPanel", "IsDummyLed", "IsDummyQrCamera", "IsDummyPhotoCamera", "Is8Ch", "IsUseNetwork" })
            {
                var p = __instance.GetType().GetProperty(name);
                values += name + "=" + (p == null ? "missing" : Convert.ToString(p.GetValue(__instance, null))) + " ";
            }
            Write("Config initialized " + values + "cwd=" + Directory.GetCurrentDirectory());
        }
        catch (Exception e) { Write("Config trace: " + e.Message); }
    }
    public static void BeforeStage(MethodBase __originalMethod) { Write("enter " + __originalMethod.DeclaringType.FullName + "." + __originalMethod.Name); }
    public static void AfterStage(MethodBase __originalMethod) { Write("leave " + __originalMethod.DeclaringType.FullName + "." + __originalMethod.Name); }
    public static void AfterBackupReady(object __instance)
    {
        if (backupRecorded) return;
        try {
            var property = __instance.GetType().GetProperty("gameSetting");
            object settings = property.GetValue(__instance, null);
            if (settings == null) return;
            Write("Backup ready MachineGroupID=" + settings.GetType().GetProperty("MachineGroupID").GetValue(settings, null) + " IsStandardSettingMachine=" + settings.GetType().GetProperty("IsStandardSettingMachine").GetValue(settings, null));
            backupRecorded = true;
        } catch (Exception e) { Write("Backup observation: " + e.Message); backupRecorded = true; }
    }
    static void Snapshot(string phase)
    {
        try
        {
            frames++;
            string state = "";
            if (manager != null)
                foreach (string name in Flags)
                {
                    FieldInfo f = manager.GetField(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                    state += name + "=" + (f == null ? "missing" : Convert.ToString(f.GetValue(null))) + " ";
                }
            state += "escape=" + Input.GetKeyDown(KeyCode.Escape);
            state += " focused=" + Application.isFocused + " background=" + Application.runInBackground;
            state += " process=" + CurrentProcesses();
            if (state != previous || frames % 600 == 0)
            {
                Write(phase + " frame=" + frames + " " + state + " renderingWidth=" + Display.main.renderingWidth);
                try { var info = AMDaemon.Error.Info; Write("AM error=" + (info == null ? "null" : (info.IsOccurred + " number=" + info.Number + " sub=" + info.SubNumber + " message=" + info.Message))); }
                catch (Exception e) { Write("AM status trace: " + e.Message); }
                try {
                    Write("Network available=" + AMDaemon.Network.IsAvailable + " LAN=" + AMDaemon.Network.IsLanAvailable + " location=" + AMDaemon.Network.IsLocationLanAvailable + " WAN=" + AMDaemon.Network.IsWanAvailable + " AuthAvailable=" + AMDaemon.Allnet.Auth.IsAvailable + " AuthGood=" + AMDaemon.Allnet.Auth.IsGood);
                    var test = AMDaemon.Network.PowerOnTestInfo;
                    if (test != null) {
                        Write("PowerOn network running=" + test.IsRunning + " complete=" + test.IsCompleted);
                        foreach (var item in test.AvailableItems)
                            Write("PowerOn network item=" + item + " state=" + test.GetState(item) + " result=" + test.GetResult(item));
                    }
                } catch (Exception e) { Write("Network observation: " + e.Message); }
                previous = state;
            }
        }
        catch (Exception e) { if (frames < 3) Write("snapshot error: " + e); }
    }
    static object Field(object obj, string name)
    {
        if (obj == null) return null;
        FieldInfo f = obj.GetType().GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        return f == null ? null : f.GetValue(obj);
    }
    static void KeyboardPath()
    {
        try {
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies()) {
                if (a.GetName().Name != "Assembly-CSharp") continue;
                Type mecha = a.GetType("IO.MechaManager");
                object jvs = mecha.GetProperty("Jvs", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic).GetValue(null, null);
                Write("keyboard path MechaInitialized=" + mecha.GetProperty("IsInitialized", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic).GetValue(null, null) + " JvsReady=" + Field(jvs, "_isReady"));
                IEnumerable switches = Field(jvs, "_switch") as IEnumerable;
                if (switches == null) continue;
                foreach (object item in switches)
                    Write("keyboard switch player=" + Field(item, "_playerNo") + " subKey=" + Field(item, "_subKey") + " on=" + Field(item, "_isStateOn") + " trigger=" + Field(item, "_isTriggerOn"));
            }
        } catch (Exception e) { Write("keyboard path observation: " + e.Message); }
    }
    static string CurrentProcesses()
    {
        object main = Field(gameObject, "main"), pm = Field(main, "_processManager");
        IEnumerable list = Field(pm, "_processList") as IEnumerable;
        if (list == null) return "unavailable";
        string result = "";
        foreach (object item in list)
        {
            object proc = item;
            PropertyInfo value = proc.GetType().GetProperty("Value");
            if (value != null) proc = value.GetValue(proc, null);
            if (proc == null) continue;
            if (proc.GetType().Namespace != "Process")
                foreach (FieldInfo f in proc.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                    if (f.FieldType.Namespace == "Process") { proc = f.GetValue(proc); break; }
            if (proc == null) continue;
            result += proc.GetType().Name;
            foreach (FieldInfo f in proc.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
                if (f.FieldType.IsEnum) result += "(" + f.Name + "=" + f.GetValue(proc) + ")";
            result += ";";
        }
        return result;
    }
    public override void OnApplicationQuit() { Snapshot("OnApplicationQuit"); Write("application quit"); }
}
