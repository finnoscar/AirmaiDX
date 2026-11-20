using System;
using System.IO;
using System.Reflection;
using System.Diagnostics;
using UnityEngine;
using AquaMai.Core.Helpers;
class MouseInputTests {
 static void Assert(bool value,string message){if(!value)throw new Exception(message);}
 static void Frame(float x,float y,bool held=true){Time.frameCount++;Time.realtimeSinceStartup+=.02f;Input.mousePosition=new Vector3(x,y,0);Input.held=held;Input.down=false;}
 static void Set(Type type,string name,object value){type.GetField(name,BindingFlags.Static|BindingFlags.NonPublic).SetValue(null,value);}
 static ulong Dummy(MouseTouchPanel panel,ulong existing=0){AirmaiMouseInput.AfterDummyTouch(panel,ref existing);return existing;}
 static void Fresh(Type type){var clock=(Stopwatch)type.GetField("Clock",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null);Set(type,"lastSample",clock.ElapsedMilliseconds);}
 static ulong seq,stamp;
 static void Controller(ushort flags,ulong touch,ushort buttons){
  using(var s=new MemoryStream())using(var w=new BinaryWriter(s)){
   w.Write(new byte[]{65,77,67,73});w.Write((ushort)1);w.Write(flags);w.Write(seq+1);w.Write(stamp+1);
   w.Write(touch);w.Write(0UL);w.Write(buttons);w.Write((ushort)0);w.Write((ushort)0);w.Write((ushort)0);w.Write(56U);w.Write(0U);
   AirmaiControllerInput.ApplyPacket(s.ToArray(),ref seq,ref stamp);
  }
 }
 public static void Main(){
  Vector2 p;
  Assert(AirmaiMouseInput.MapPoint(1280,720,2560,1440,1080,1920,out p)&&p.x==540&&p.y==960,"landscape center maps to portrait scene");
  Assert(!AirmaiMouseInput.MapPoint(100,720,2560,1440,1080,1920,out p),"black bars cannot touch game");
  Assert(AirmaiMouseInput.MapPoint(1280,720,2560,1440,2160,3840,out p)&&p.x==1080&&p.y==1920,"4K render mapping");
  Assert(AirmaiMouseInput.MapPoint(540,960,1080,1920,1080,1920,out p)&&p.x==540&&p.y==960,"portrait mapping");
  Assert(!AirmaiMouseInput.MapPoint(-1,0,1080,1920,1080,1920,out p),"outside window");
  Assert(!AirmaiMouseInput.MapPoint(0,0,0,0,1080,1920,out p),"invalid dimensions");
  File.WriteAllLines(@"C:\AirmaiMouse.cfg",new[]{"AIRMAI_MOUSE_V1","en"});
  var sensor=new MeshButton{GetTouchPanelArea=(Manager.InputManager.TouchPanelArea)3,targetGraphic=new CustomGraphic()};
  sensor.targetGraphic.vertex.AddRange(new[]{new Vector2(530,950),new Vector2(550,950),new Vector2(550,970),new Vector2(530,970)});
  var panel=new MouseTouchPanel{PlayerID=0,sensors=new[]{sensor}};
  Manager.InputManager.MouseTouchPanel[0]=panel;
  Camera.main=new Camera{targetTexture=new RenderTexture{name="Airmai scene render",width=1080,height=1920}};
  var mod=new AirmaiMouseInput();mod.OnInitializeMelon();Frame(1280,720,false);mod.OnUpdate();Frame(1280,720);
  Assert(JvsSwitchHook.buttons!=null&&JvsSwitchHook.aux!=null,"provider registration");
  Assert(JvsSwitchHook.buttons(0,4)&&!JvsSwitchHook.buttons(1,4)&&!JvsSwitchHook.buttons(0,1),"outer button and player isolation");
  Assert(TouchStatusProvider.providers[0](0)==(1UL<<3),"mouse registers through native touch provider");
  Frame(1280,720,false);Assert(!AirmaiMouseInput.ReadButton(0,4),"mouse release");
  Assert(TouchStatusProvider.providers[0](0)==0,"touch release");
  sensor.GetTouchPanelArea=(Manager.InputManager.TouchPanelArea)16;Frame(1280,720);Assert(TouchStatusProvider.providers[0](0)==(1UL<<16)&&!AirmaiMouseInput.ReadButton(0,1),"center touch does not press outer button");
  Assert(Dummy(panel)==(1UL<<16),"dummy panel receives center mouse click without IO provider polling");
  Assert(Dummy(panel,1UL<<8)==((1UL<<8)|(1UL<<16)),"dummy panel preserves existing input");
  Assert(Dummy(new MouseTouchPanel{PlayerID=1})==0,"dummy panel respects player identity");
  Frame(1280,720,false);Assert(Dummy(panel)==0,"dummy panel releases center click");
  Frame(100,720);Assert(TouchStatusProvider.providers[0](0)==0,"black bar release");
  Frame(1280,720);Application.isFocused=false;Assert(TouchStatusProvider.providers[0](0)==0,"focus loss releases input");
  Assert(!JvsSwitchHook.aux().select1P,"background does not start game");
  Frame(1280,720,false);Application.isFocused=true;mod.OnUpdate();
  Frame(1280,720,false);Input.right=true;Assert(JvsSwitchHook.aux().select1P,"right-click select");
  Input.right=false;Assert(!JvsSwitchHook.aux().select1P,"right-click release");
  Frame(20,20);Assert(TouchStatusProvider.providers[0](0)==0,"toolbar does not touch game");
  bool result=true;Assert(!AirmaiMouseInput.BeforeStockMouse(ref result)&&!result,"stock unscaled mouse path disabled");
  GUI.click=true;mod.OnGUI();GUI.click=false;
  var toolbar=AirmaiMouseInput.ReadAux<JvsSwitchHook.AuxiliaryState>();
  Assert(toolbar.select1P&&toolbar.service&&GUI.calls==2,"visible mouse toolbar delivers start and credit");

  // Real sensor geometry, not an IsInside stub returning a preselected area.
  // B4/B5 drive the game's beginner/advanced preset switch.
  var preset=new MeshButton{GetTouchPanelArea=(Manager.InputManager.TouchPanelArea)11,targetGraphic=new CustomGraphic()};
  preset.targetGraphic.vertex.AddRange(new[]{new Vector2(610,310),new Vector2(650,310),new Vector2(650,350),new Vector2(610,350)});
  var presetPanel=new MouseTouchPanel{PlayerID=0,sensors=new[]{preset}};
  Manager.InputManager.MouseTouchPanel[0]=presetPanel;
  int[,] outputs={{2560,1440},{1920,1080},{3840,2160},{2160,3840},{1440,2560},{1728,1117},{1080,1920}};
  int[] renders={720,1080,1440,2160};
  foreach(int rw in renders)for(int o=0;o<outputs.GetLength(0);o++) {
   int rh=rw*16/9;Screen.width=outputs[o,0];Screen.height=outputs[o,1];
   Camera.main.targetTexture=new RenderTexture{name="Airmai scene render",width=rw,height=rh};
   float scale=Math.Min((float)Screen.width/rw,(float)Screen.height/rh);
   float x=(Screen.width-rw*scale)/2+630*rw/1080f*scale;
   float y=(Screen.height-rh*scale)/2+330*rw/1080f*scale;
   Frame(x,y);Assert(AirmaiMouseInput.ReadTouch(0)==(1UL<<11),"B4 preset hit across output/render matrix");
   Assert(!AirmaiMouseInput.ReadButton(0,4),"preset cannot become outer key");
   Frame(x,y,false);Assert(Dummy(presetPanel)==0,"preset releases across output/render matrix");
  }
  Screen.width=2560;Screen.height=1440;
  Camera.main.targetTexture=new RenderTexture{name="Airmai scene render",width=1080,height=1920};
  preset.targetGraphic.transform.offset=new Vector3(100,0,0);
  Frame(1280+(630-540)*.75f,330*.75f);Assert(AirmaiMouseInput.ReadTouch(0)==0,"old projected sensor position no longer hits after movement");
  Frame(1280+(730-540)*.75f,330*.75f);Assert(AirmaiMouseInput.ReadTouch(0)==(1UL<<11),"current transform controls sensor hit without Awake cache");
  preset.GetTouchPanelArea=(Manager.InputManager.TouchPanelArea)12;
  Frame(1280+(730-540)*.75f,330*.75f);Assert(AirmaiMouseInput.ReadTouch(0)==(1UL<<12),"B5 reverse preset switch");
  Manager.InputManager.MouseTouchPanel[0]=panel;
  Frame(1280,720,false);mod.OnUpdate();

  // HDX transport alone cannot suppress mouse until the game provider exists.
  var hdx=typeof(AirmaiHdxNativeTouch);Set(hdx,"healthy",true);Fresh(hdx);
  Frame(1280,720);Assert(AirmaiMouseInput.ReadTouch(0)!=0,"unregistered hardware keeps mouse usable");
  AirmaiHdxNativeTouch.BeforeInitialize();Assert(AirmaiHdxNativeTouch.HasLiveInput(),"HDX consumer readiness");
  Set(hdx,"latest",1UL<<5);Set(hdx,"pending",1UL<<5);
  Set(typeof(AirmaiMouseInput),"startUntil",Time.frameCount+100);Set(typeof(AirmaiMouseInput),"serviceUntil",Time.frameCount+100);
  Input.right=true;Frame(1280,720);mod.OnUpdate();
  Assert(AirmaiMouseInput.ReadTouch(0)==0&&!AirmaiMouseInput.ReadButton(0,1),"hardware suspends mouse touch and outer buttons while held");
  Assert(Dummy(panel)==0&&Dummy(panel,1UL<<5)==(1UL<<5),"dummy path suppresses mouse with hardware and preserves real input");
  Assert(!AirmaiMouseInput.ReadAux<JvsSwitchHook.AuxiliaryState>().select1P&&!AirmaiMouseInput.ReadAux<JvsSwitchHook.AuxiliaryState>().service,"hardware clears right click and toolbar pulses");
  int guiCalls=GUI.calls;GUI.click=true;mod.OnGUI();GUI.click=false;Assert(GUI.calls==guiCalls,"hardware hides mouse toolbar");
  Assert(TouchStatusProvider.providers[0](0)==(1UL<<5),"real touch survives mouse suspension without replacement");
  result=true;Assert(!AirmaiMouseInput.BeforeStockMouse(ref result)&&!result,"stock mouse remains suppressed with hardware");
  Set(hdx,"lastSample",-10000L);Frame(1280,720);
  Assert(!AirmaiHdxNativeTouch.HasLiveInput()&&TouchStatusProvider.providers[0](0)==0,"HDX silence releases real and mouse-held touches");
  Assert(!AirmaiMouseInput.ReadAux<JvsSwitchHook.AuxiliaryState>().select1P,"held right click cannot replay on fallback");
  Input.right=false;Frame(1280,720,false);mod.OnUpdate();Frame(1280,720);
  Assert(AirmaiMouseInput.ReadTouch(0)!=0,"mouse resumes after explicit release");
  Fresh(hdx);Set(hdx,"healthy",true);Frame(1280,720);
  Assert(AirmaiMouseInput.ReadTouch(0)==0,"HDX reconnection suppresses mouse again");
  Set(hdx,"healthy",false);Frame(1280,720,false);mod.OnUpdate();

  // The ADX receiver uses actual validated packets and registered APIs.
  var adx=typeof(AirmaiControllerInput);Set(adx,"touchMask",1);Controller(5,1UL<<10,4);
  Assert(!AirmaiControllerInput.HasLiveInput(),"packets without game API do not claim readiness");
  var controller=new AirmaiControllerInput();controller.OnUpdate();
  Assert(AirmaiControllerInput.HasLiveInput(),"ADX live packet and providers are ready");
  Frame(1280,720);mod.OnUpdate();Assert(AirmaiMouseInput.ReadTouch(0)==0,"ADX suppresses mouse");
  Assert(TouchStatusProvider.providers[0](0)==(1UL<<10)&&JvsSwitchHook.buttons(0,3),"real ADX touch and outer buttons survive");
  Controller(0,0,0);Frame(1280,720);Assert(AirmaiMouseInput.ReadTouch(0)==0,"ADX removal releases mouse-held input");
  Frame(1280,720,false);mod.OnUpdate();Frame(1280,720);Assert(AirmaiMouseInput.ReadTouch(0)!=0,"ADX removal resumes mouse after release");
  Controller(1,0,0);Assert(!AirmaiControllerInput.HasLiveInput(),"partial ADX input cannot suspend mouse when touch is missing");
  Controller(5,0,0);Assert(AirmaiControllerInput.HasLiveInput(),"idle zero reports still prove hardware readiness");
  Frame(1280,720);Assert(AirmaiMouseInput.ReadTouch(0)==0,"idle hardware still disables mouse");
  Set(adx,"lastSample",-10000L);Frame(1280,720,false);mod.OnUpdate();
  Frame(1280,720);Application.isFocused=false;Assert(AirmaiMouseInput.ReadTouch(0)==0,"focus loss clears pointer immediately");
  Application.isFocused=true;Assert(AirmaiMouseInput.ReadTouch(0)==0,"focus regain while held cannot press");
  Frame(1280,720,false);mod.OnUpdate();Frame(1280,720);Assert(AirmaiMouseInput.ReadTouch(0)!=0,"fresh click after focus regain");
  Assert(File.ReadAllLines(@"C:\AirmaiMouse-state.txt")[1]=="mouse","consumer mode is exposed for UI diagnostics");
  mod.OnApplicationQuit();Frame(1280,720);Assert(!AirmaiMouseInput.ReadButton(0,4),"quit releases input");
  Assert(File.ReadAllLines(@"C:\AirmaiMouse-state.txt")[1]=="keyboard","quit clears active mouse status");
  Console.WriteLine("Mouse mapping, 4K, HDX/ADX handover, provider coexistence, stale/partial reports, held-input release, toolbar and focus checks passed.");
 }
}
