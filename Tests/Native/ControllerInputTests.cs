using System;
using System.IO;
using System.Reflection;
class Test {
 static ulong seq=0,time=0;
 static void Assert(bool value,string message){if(!value)throw new Exception(message);}
 static byte[] Packet(ushort flags,ulong touch,ushort buttons,ushort aux){
  using(var s=new MemoryStream())using(var w=new BinaryWriter(s)){
   w.Write(new byte[]{65,77,67,73});w.Write((ushort)1);w.Write(flags);w.Write(++seq);w.Write(seq*10);
   w.Write(touch);w.Write(0UL);w.Write(buttons);w.Write((ushort)0);w.Write(aux);w.Write((ushort)0);w.Write(56U);w.Write(0U);return s.ToArray();
  }
 }
 public struct Aux {public bool select1P,select2P,service,test;}
 public static void Main(){
  ulong previous=0;
  byte[] press=Packet(5,1UL<<33,128,13);AirmaiControllerInput.ApplyPacket(press,ref previous,ref time);
  Assert(AirmaiControllerInput.ReadButton(0,8),"outer8");Assert(!AirmaiControllerInput.ReadButton(1,8),"player isolation");
  Assert(AirmaiControllerInput.ReadTouch(0)==1UL<<33,"touch34");
  Aux aux=AirmaiControllerInput.ReadAux<Aux>();Assert(aux.select1P&&aux.service&&aux.test&&!aux.select2P,"auxiliary mapping");
  byte[] release=Packet(5,0,0,0);AirmaiControllerInput.ApplyPacket(release,ref previous,ref time);
  Assert(!AirmaiControllerInput.ReadButton(0,8),"button release");Assert(AirmaiControllerInput.ReadTouch(0)==0,"touch release");
  // A press/release arriving between game reads survives one read only.
  AirmaiControllerInput.ApplyPacket(Packet(5,1,1,0),ref previous,ref time);
  AirmaiControllerInput.ApplyPacket(Packet(5,0,0,0),ref previous,ref time);
  Assert(AirmaiControllerInput.ReadButton(0,1)&&!AirmaiControllerInput.ReadButton(0,1),"short outer press");
  Assert(AirmaiControllerInput.ReadTouch(0)==1&&AirmaiControllerInput.ReadTouch(0)==0,"short touch");
  AirmaiControllerInput.ApplyPacket(Packet(5,1,1,0),ref previous,ref time);
  AirmaiControllerInput.ApplyPacket(Packet(0,0,0,0),ref previous,ref time);
  Assert(!AirmaiControllerInput.ReadButton(0,1)&&AirmaiControllerInput.ReadTouch(0)==0,"disconnect releases pending states");
  foreach(var broken in new[]{press,new byte[55],Packet(5,1UL<<34,0,0),Packet(32,0,0,0),Packet(1,0,256,0)}){
   bool rejected=false;try{AirmaiControllerInput.ApplyPacket(broken,ref previous,ref time);}catch(InvalidDataException){rejected=true;}
   Assert(rejected,"malformed or replay packet rejected");
  }
  AirmaiControllerInput.ApplyPacket(Packet(5,1,1,0),ref previous,ref time);
  typeof(AirmaiControllerInput).GetField("lastSample",BindingFlags.Static|BindingFlags.NonPublic).SetValue(null,-10000L);
  Assert(!AirmaiControllerInput.ReadButton(0,1)&&AirmaiControllerInput.ReadTouch(0)==0,"stale connection releases state");
  Console.WriteLine("Native controller packet, player isolation, auxiliary, latch, stale release and malformed packet checks passed.");
 }
}
