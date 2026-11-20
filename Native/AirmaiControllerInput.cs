using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Diagnostics;
using System.Threading;
using MelonLoader;
using HarmonyLib;

[assembly: MelonInfo(typeof(AirmaiControllerInput), "Airmai Controller Input", "0.1.0", "Airmai")]
// Real hardware states only. AquaMai public provider APIs are checked at runtime;
// no keyboard injection, account patches or fabricated controller responses.
public sealed class AirmaiControllerInput : MelonMod {
    static readonly object Gate=new object();
    static readonly Stopwatch Clock=Stopwatch.StartNew();
    static readonly ulong Mask=(1UL<<34)-1;
    static readonly ulong[] Touch=new ulong[2], PendingTouch=new ulong[2];
    static readonly ushort[] Buttons=new ushort[2], PendingButtons=new ushort[2], Aux=new ushort[2], PendingAux=new ushort[2];
    static readonly Delegate[] TouchRoots=new Delegate[2];
    static Delegate buttonRoot,auxRoot;
    static int flags, touchMask;
    static long lastSample=-10000,lastLog,lastRegister=-1000;
    static bool quitting,apiLogged;
    static TcpClient active;
    static void Log(string text){try{lock(Gate)File.AppendAllText("C:\\AirmaiDX\\Package\\AirmaiControllerInput.log",DateTime.UtcNow.ToString("O")+" "+text+"\r\n");}catch{}}
    public override void OnInitializeMelon(){
        try{
            string[] cfg=File.ReadAllLines("C:\\AirmaiController.cfg");
            if(cfg.Length!=4||!int.TryParse(cfg[3],out touchMask)||touchMask<0||touchMask>3)throw new InvalidDataException();
        }catch{Log("Invalid controller configuration; native input disabled.");return;}
        var thread=new Thread(Receive);thread.IsBackground=true;thread.Name="Airmai controller IPC";thread.Start();
        foreach(Assembly a in AppDomain.CurrentDomain.GetAssemblies()){
            Type type=a.GetType("IO.NewTouchPanel");if(type==null)continue;
            MethodInfo method=type.GetMethod("Initialize",BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic);
            if(method!=null)new HarmonyLib.Harmony("airmai.controller.register").Patch(method,new HarmonyMethod(typeof(AirmaiControllerInput).GetMethod("BeforeInitialize")));
        }
        TryRegister();
    }
    public static void BeforeInitialize(){TryRegister();}
    static bool Fresh(){return Clock.ElapsedMilliseconds-lastSample<=200;}
    // Readiness is based on a valid live device packet AND the game providers,
    // never on USB presence or an open socket with no decoded input reports.
    public static bool HasLiveInput(){
        lock(Gate){
            if(quitting||!Fresh()||(flags&3)==0||buttonRoot==null||auxRoot==null)return false;
            for(int p=0;p<2;p++)if((flags&(1<<p))!=0 && (touchMask&(1<<p))!=0 &&
                ((flags&(4<<p))==0||TouchRoots[p]==null))return false;
            return true;
        }
    }
    static void Clear(){flags=0;Array.Clear(Touch,0,2);Array.Clear(PendingTouch,0,2);Array.Clear(Buttons,0,2);Array.Clear(PendingButtons,0,2);Array.Clear(Aux,0,2);Array.Clear(PendingAux,0,2);}
    public static bool ReadButton(int player,int button){
        if(player<0||player>1||button<1||button>8)return false;
        lock(Gate){
            if(!Fresh()){Clear();return false;}
            ushort mask=(ushort)(1<<(button-1));bool result=((Buttons[player]|PendingButtons[player])&mask)!=0;
            PendingButtons[player]&=(ushort)~mask;return result;
        }
    }
    public static ulong ReadTouch(int player){
        if(player<0||player>1)return 0;
        lock(Gate){if(!Fresh()){Clear();return 0;}ulong value=Touch[player]|PendingTouch[player];PendingTouch[player]=0;return value;}
    }
    public static T ReadAux<T>(){
        object value=Activator.CreateInstance(typeof(T));ushort bits=0;
        lock(Gate){if(!Fresh())Clear();for(int p=0;p<2;p++){bits|=(ushort)(Aux[p]|PendingAux[p]);PendingAux[p]=0;}}
        string[] names={"select1P","select2P","service","test"};
        for(int i=0;i<names.Length;i++){FieldInfo field=typeof(T).GetField(names[i]);if(field!=null&&field.FieldType==typeof(bool))field.SetValue(value,(bits&(1<<i))!=0);}
        // Public AquaMai AuxiliaryState has no coin input. Coin remains on the
        // existing keyboard binding; never translate it into a card scan.
        return (T)value;
    }
    static MethodInfo Method(Type type,string name){return type==null?null:type.GetMethod(name,BindingFlags.Static|BindingFlags.Public);}
    static void TryRegister(){
        if(Clock.ElapsedMilliseconds-lastRegister<500)return;lastRegister=Clock.ElapsedMilliseconds;
        try{
            foreach(Assembly assembly in AppDomain.CurrentDomain.GetAssemblies()){
                Type jvs=assembly.GetType("AquaMai.Core.Helpers.JvsSwitchHook");
                MethodInfo addButton=Method(jvs,"RegisterButtonChecker"),addAux=Method(jvs,"RegisterAuxiliaryStateProvider");
                if(buttonRoot==null&&addButton!=null){
                    Type delegateType=addButton.GetParameters()[0].ParameterType;
                    Delegate candidate=Delegate.CreateDelegate(delegateType,typeof(AirmaiControllerInput).GetMethod("ReadButton"));
                    addButton.Invoke(null,new object[]{candidate});buttonRoot=candidate;Log("Registered native outer buttons through AquaMai JvsSwitchHook.");
                }
                if(auxRoot==null&&addAux!=null){
                    Type delegateType=addAux.GetParameters()[0].ParameterType;Type state=delegateType.GetMethod("Invoke").ReturnType;
                    foreach(string name in new[]{"select1P","select2P","service","test"}){
                        FieldInfo field=state.GetField(name);if(field==null||field.FieldType!=typeof(bool))throw new InvalidDataException("Unknown auxiliary API");
                    }
                    Delegate candidate=Delegate.CreateDelegate(delegateType,typeof(AirmaiControllerInput).GetMethod("ReadAux").MakeGenericMethod(state));
                    addAux.Invoke(null,new object[]{candidate});auxRoot=candidate;Log("Registered native auxiliary buttons.");
                }
                MethodInfo addTouch=Method(assembly.GetType("AquaMai.Core.Helpers.TouchStatusProvider"),"RegisterTouchStatusProvider");
                if(addTouch!=null)for(int p=0;p<2;p++)if((touchMask&(1<<p))!=0&&TouchRoots[p]==null){
                    Type delegateType=addTouch.GetParameters()[1].ParameterType;
                    Delegate candidate=Delegate.CreateDelegate(delegateType,typeof(AirmaiControllerInput).GetMethod("ReadTouch"));
                    addTouch.Invoke(null,new object[]{p,candidate});TouchRoots[p]=candidate;Log("Registered native touch for player "+(p+1));
                }
            }
        }catch(Exception e){if(!apiLogged){apiLogged=true;Log("Controller API unavailable: "+e.GetType().Name+"; use keyboard fallback and export diagnostics.");}}
    }
    public override void OnUpdate(){
        TryRegister();
        if(Clock.ElapsedMilliseconds-lastLog<2000)return;lastLog=Clock.ElapsedMilliseconds;
        lock(Gate){if(!Fresh())Clear();Log("transport="+Fresh()+" players="+(flags&3)+" buttonsRegistered="+(buttonRoot!=null)+" auxiliaryRegistered="+(auxRoot!=null)+" touch1Registered="+(TouchRoots[0]!=null)+" touch2Registered="+(TouchRoots[1]!=null));}
    }
    static void ReadExact(Stream stream,byte[] data){int at=0;while(at<data.Length){int count=stream.Read(data,at,data.Length-at);if(count==0)throw new EndOfStreamException();at+=count;}}
    public static void ApplyPacket(byte[] data,ref ulong previous,ref ulong previousTime){
        if(data.Length!=56)throw new InvalidDataException();
        int nextFlags=BitConverter.ToUInt16(data,6);ulong seq=BitConverter.ToUInt64(data,8),time=BitConverter.ToUInt64(data,16);
                if(data[0]!=65||data[1]!=77||data[2]!=67||data[3]!=73||BitConverter.ToUInt16(data,4)!=1||nextFlags>15||seq<=previous||time<previousTime||BitConverter.ToUInt32(data,48)!=56||BitConverter.ToUInt32(data,52)!=0)throw new InvalidDataException();
                previous=seq;previousTime=time;
                for(int p=0;p<2;p++)if((BitConverter.ToUInt64(data,24+p*8)&~Mask)!=0||BitConverter.ToUInt16(data,40+p*2)>255||BitConverter.ToUInt16(data,44+p*2)>31)throw new InvalidDataException();
                lock(Gate){
                    lastSample=Clock.ElapsedMilliseconds;flags=nextFlags;
                    for(int p=0;p<2;p++){
                        bool live=(flags&(1<<p))!=0;
                        Touch[p]=live&&(flags&(4<<p))!=0?BitConverter.ToUInt64(data,24+p*8):0;
                        Buttons[p]=live?BitConverter.ToUInt16(data,40+p*2):(ushort)0;Aux[p]=live?BitConverter.ToUInt16(data,44+p*2):(ushort)0;
                        PendingTouch[p]=live?PendingTouch[p]|Touch[p]:0;
                        PendingButtons[p]=live?(ushort)(PendingButtons[p]|Buttons[p]):(ushort)0;PendingAux[p]=live?(ushort)(PendingAux[p]|Aux[p]):(ushort)0;
                    }
                }
    }
    static void Receive(){while(!quitting){try{
        string[] cfg=File.ReadAllLines("C:\\AirmaiController.cfg");
        if(cfg.Length!=4||cfg[0]!="AIRMAI_CONTROLLER_V1"||cfg[1]!="59186"||cfg[2].Length!=64)throw new InvalidDataException();
        byte[] token=new byte[32];for(int i=0;i<32;i++)token[i]=Convert.ToByte(cfg[2].Substring(i*2,2),16);
        using(TcpClient client=new TcpClient()){
            active=client;client.NoDelay=true;client.ReceiveTimeout=500;client.Connect(IPAddress.Loopback,59186);
            NetworkStream stream=client.GetStream();stream.Write(token,0,32);Array.Clear(token,0,32);
            byte[] data=new byte[56];ulong previous=0,previousTime=0;
            while(!quitting){
                ReadExact(stream,data);ApplyPacket(data,ref previous,ref previousTime);
            }
        }
    }catch(Exception e){lock(Gate)Clear();if(!quitting)Log("Controller transport unavailable: "+e.GetType().Name);Thread.Sleep(500);}finally{active=null;}}}
    public override void OnApplicationQuit(){quitting=true;try{if(active!=null)active.Close();}catch{}lock(Gate)Clear();}
}
