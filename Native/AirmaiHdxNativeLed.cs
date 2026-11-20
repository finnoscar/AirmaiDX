using System;
using System.IO;
using System.Reflection;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Collections.Generic;
using MelonLoader;
using HarmonyLib;

[assembly: MelonInfo(typeof(AirmaiHdxNativeLed),"Airmai HDX Native LED","0.1.0","Airmai local hardware experiment")]
// Mirrors actual player-1 game RGB requests. No fabricated hardware checks.
public sealed class AirmaiHdxNativeLed : MelonMod {
    static readonly object Gate=new object();
    static readonly Queue<byte[]> Queue=new Queue<byte[]>();
    static readonly AutoResetEvent Wake=new AutoResetEvent(false);
    static bool quitting,connected;
    static TcpClient active;
    static long queued,sent,overflow;
    static DateTime lastReport=DateTime.MinValue;
    static readonly string LogPath="C:\\AirmaiDX\\Package\\AirmaiHdxNativeLed.log";
    static void Log(string s){try{lock(Gate)File.AppendAllText(LogPath,DateTime.UtcNow.ToString("O")+" "+s+"\r\n");}catch{}}
    public override void OnInitializeMelon(){
        var harmony=new HarmonyLib.Harmony("airmai.hdx.native-led");
        foreach(Assembly a in AppDomain.CurrentDomain.GetAssemblies()){
            Type t=a.GetType("Mecha.Bd15070_4Control");if(t==null)continue;
            foreach(MethodInfo m in t.GetMethods(BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic)){
                if(Array.IndexOf(new[]{"SetColor","SetColorMulti","SetColorMultiFade","SetColorUpdate","SetLedAllOff"},m.Name)<0)continue;
                harmony.Patch(m,new HarmonyMethod(typeof(AirmaiHdxNativeLed).GetMethod("Forward")));
                Log("Mirroring verified game RGB method "+m.Name);
            }
        }
        var thread=new Thread(Send);thread.IsBackground=true;thread.Name="Airmai HDX LED output";thread.Start();
    }
    static byte Component(object color,string name){return Convert.ToByte(color.GetType().GetField(name).GetValue(color));}
    static void Enqueue(byte[] data){lock(Gate){if(Queue.Count>=4096){overflow++;return;}Queue.Enqueue(data);queued++;}Wake.Set();}
    public static void Forward(object __instance,MethodBase __originalMethod,object[] __args){
        FieldInfo board=__instance.GetType().GetField("_bdID",BindingFlags.Instance|BindingFlags.NonPublic);
        if(board==null||Convert.ToInt32(board.GetValue(__instance))!=0)return;
        string method=__originalMethod.Name;
        if(method=="SetColor"){
            int index=Convert.ToInt32(__args[0]);if(index<0||index>=8)return;
            object color=__args[1];Enqueue(new byte[]{0x31,(byte)index,Component(color,"r"),Component(color,"g"),Component(color,"b")});
        }else if(method=="SetColorMulti"||method=="SetColorMultiFade"){
            object color=__args[0];byte speed=Convert.ToByte(__args[1]);
            Enqueue(new byte[]{(byte)(method=="SetColorMulti"?0x32:0x33),0,8,0,Component(color,"r"),Component(color,"g"),Component(color,"b"),speed});
        }else if(method=="SetLedAllOff"){
            Enqueue(new byte[]{0x32,0,8,0,0,0,0,0});Enqueue(new byte[]{0x3c});
        }else if(method=="SetColorUpdate")Enqueue(new byte[]{0x3c});
    }
    static void ReadExact(Stream s,byte[] b){int i=0;while(i<b.Length){int n=s.Read(b,i,b.Length-i);if(n==0)throw new EndOfStreamException();i+=n;}}
    static void Send(){
        while(!quitting){try{
            string[] cfg=File.ReadAllLines("C:\\AirmaiHDXLED.cfg");
            if(cfg.Length!=3||cfg[0]!="AIRMAI_HDX_LED_V1"||cfg[1]!="59185"||cfg[2].Length!=64)throw new InvalidDataException();
            byte[] token=new byte[32];for(int i=0;i<32;i++)token[i]=Convert.ToByte(cfg[2].Substring(i*2,2),16);
            using(TcpClient c=new TcpClient()){
                active=c;c.NoDelay=true;c.SendTimeout=1000;c.ReceiveTimeout=1000;c.Connect(IPAddress.Loopback,59185);
                NetworkStream stream=c.GetStream();stream.Write(token,0,32);Array.Clear(token,0,32);
                byte[] ack=new byte[4];ReadExact(stream,ack);
                if(ack[0]!=76||ack[1]!=69||ack[2]!=68||ack[3]!=49)throw new InvalidDataException();
                connected=true;Log("Connected to initialized real HDX LED backend; original game RGB values, no brightness cap.");
                while(!quitting){
                    byte[] data=null;lock(Gate){if(Queue.Count>0)data=Queue.Dequeue();}
                    if(data==null){Wake.WaitOne(100);continue;}
                    byte[] length={(byte)data.Length,0};stream.Write(length,0,2);stream.Write(data,0,data.Length);sent++;
                }
            }
        }catch(Exception e){connected=false;Log("LED backend unavailable: "+e.GetType().Name);Thread.Sleep(500);}finally{active=null;}}
    }
    public override void OnUpdate(){if((DateTime.UtcNow-lastReport).TotalSeconds<2)return;lastReport=DateTime.UtcNow;lock(Gate)Log("connected="+connected+" queued="+queued+" sent="+sent+" pending="+Queue.Count+" overflow="+overflow);}
    public override void OnApplicationQuit(){quitting=true;Wake.Set();try{if(active!=null)active.Close();}catch{}}
}
