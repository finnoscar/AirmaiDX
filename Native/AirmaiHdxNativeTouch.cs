using System;
using System.IO;
using System.Reflection;
using System.Net;
using System.Net.Sockets;
using System.Diagnostics;
using System.Threading;
using MelonLoader;
using HarmonyLib;

[assembly: MelonInfo(typeof(AirmaiHdxNativeTouch), "Airmai HDX Native Touch", "0.1.0", "Airmai local hardware experiment")]
// Receives real HDX samples only. No synthetic touches or account/network patches.
public sealed class AirmaiHdxNativeTouch : MelonMod {
    static readonly object Gate = new object();
    static readonly ulong Mask = (1UL<<35)-1;
    static readonly Stopwatch Clock = Stopwatch.StartNew();
    static ulong latest, pending, packets, consumed, nonzero;
    static long lastSample=-10000, lastReport;
    static bool healthy, registered, quitting;
    static Delegate providerRoot;
    static TcpClient activeClient;
    static readonly string LogPath="C:\\AirmaiDX\\Package\\AirmaiHdxNativeTouch.log";
    static void Log(string text) {
        try { lock(Gate) File.AppendAllText(LogPath,DateTime.UtcNow.ToString("O")+" "+text+"\r\n"); } catch {}
    }
    public override void OnInitializeMelon() {
        Log("Starting real HDX native touch receiver; only player 1; stale samples release within 200ms.");
        var thread=new Thread(Receive);thread.IsBackground=true;thread.Name="Airmai HDX touch IPC";thread.Start();
        foreach(Assembly a in AppDomain.CurrentDomain.GetAssemblies()) {
            Type t=a.GetType("IO.NewTouchPanel");if(t==null)continue;
            MethodInfo initialize=t.GetMethod("Initialize",BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);
            if(initialize!=null)new HarmonyLib.Harmony("airmai.hdx.native-touch-register").Patch(initialize,
                new HarmonyMethod(typeof(AirmaiHdxNativeTouch).GetMethod("BeforeInitialize")));
        }
    }
    public static void BeforeInitialize(){TryRegister();}
    public static bool HasLiveInput(){lock(Gate)return !quitting&&registered&&healthy&&Clock.ElapsedMilliseconds-lastSample<=200;}
    public override void OnUpdate() {
        TryRegister();
        if(Clock.ElapsedMilliseconds-lastReport<1000)return;
        lastReport=Clock.ElapsedMilliseconds;
        lock(Gate) {
            if(Clock.ElapsedMilliseconds-lastSample>200){healthy=false;latest=pending=0;}
            Log("health="+healthy+" registered="+registered+" packets="+packets+" consumed="+consumed+" nonzero="+nonzero+" bitmap="+latest);
        }
    }
    static void TryRegister() {
        lock(Gate){if(registered||!healthy||Clock.ElapsedMilliseconds-lastSample>200)return;}
        foreach(Assembly a in AppDomain.CurrentDomain.GetAssemblies()) {
            Type t=a.GetType("AquaMai.Core.Helpers.TouchStatusProvider");if(t==null)continue;
            MethodInfo method=t.GetMethod("RegisterTouchStatusProvider",BindingFlags.Static|BindingFlags.Public);
            if(method==null)return;
            ParameterInfo[] p=method.GetParameters();
            if(p.Length!=2||p[0].ParameterType!=typeof(int))throw new InvalidOperationException("Unexpected verified touch provider API");
            providerRoot=Delegate.CreateDelegate(p[1].ParameterType,typeof(AirmaiHdxNativeTouch).GetMethod("ReadTouch"));
            method.Invoke(null,new object[]{0,providerRoot});
            registered=true;Log("Registered real HDX stream through AquaMai TouchStatusProvider for player 1.");return;
        }
    }
    public static ulong ReadTouch(int playerNo) {
        if(playerNo!=0)return 0;
        lock(Gate) {
            if(!healthy||Clock.ElapsedMilliseconds-lastSample>200){latest=pending=0;healthy=false;return 0;}
            ulong result=latest|pending;pending=0;consumed++;if(result!=0)nonzero++;return result;
        }
    }
    static void ReadExact(Stream stream,byte[] data) {
        int at=0;while(at<data.Length){int n=stream.Read(data,at,data.Length-at);if(n==0)throw new EndOfStreamException();at+=n;}
    }
    static void Receive() {
        while(!quitting) {
            try {
                string[] lines=File.ReadAllLines("C:\\AirmaiHDXBridge.cfg");int port;
                if(lines.Length!=3||lines[0]!="AIRMAI_HDX_TOUCH_V1"||!int.TryParse(lines[1],out port)||port!=59184||lines[2].Length!=64)
                    throw new InvalidDataException("Invalid local bridge configuration");
                byte[] token=new byte[32];for(int i=0;i<token.Length;i++)token[i]=Convert.ToByte(lines[2].Substring(i*2,2),16);
                using(TcpClient client=new TcpClient()) {
                    activeClient=client;client.NoDelay=true;client.ReceiveTimeout=500;client.SendTimeout=500;
                    client.Connect(IPAddress.Loopback,port);
                    NetworkStream stream=client.GetStream();stream.Write(token,0,token.Length);Array.Clear(token,0,token.Length);
                    byte[] data=new byte[40];ulong previous=0,previousTime=0;
                    while(!quitting) {
                        ReadExact(stream,data);
                        ulong sequence=BitConverter.ToUInt64(data,8),time=BitConverter.ToUInt64(data,16),bits=BitConverter.ToUInt64(data,24);
                        ushort flags=BitConverter.ToUInt16(data,6);
                        if(data[0]!=72||data[1]!=68||data[2]!=88||data[3]!=84||BitConverter.ToUInt16(data,4)!=1||flags>1||
                           BitConverter.ToUInt32(data,32)!=40||BitConverter.ToUInt32(data,36)!=0||sequence<=previous||time<previousTime||(bits&~Mask)!=0)
                            throw new InvalidDataException("Invalid native touch packet");
                        previous=sequence;previousTime=time;
                        lock(Gate) {
                            healthy=flags==1;lastSample=Clock.ElapsedMilliseconds;packets++;
                            latest=healthy?bits:0;pending=healthy?(pending|bits):0;
                        }
                    }
                }
            } catch(Exception e) {
                lock(Gate){healthy=false;latest=pending=0;}
                Log("Native touch unavailable: "+e.GetType().Name);Thread.Sleep(500);
            } finally {activeClient=null;}
        }
    }
    public override void OnApplicationQuit(){quitting=true;try{if(activeClient!=null)activeClient.Close();}catch{}lock(Gate){healthy=false;latest=pending=0;}}
}
