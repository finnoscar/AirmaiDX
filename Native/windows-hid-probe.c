/* Self-authored read-only HID/USB probe. No installer, network client, firmware
 * calls, HID output/feature writes, game loading, or third-party runtime. */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <hidpi.h>

void *memset(void *p,int v,size_t n){volatile unsigned char *b=p;for(size_t i=0;i<n;i++)b[i]=(unsigned char)v;return p;}
void *memcpy(void *p,const void *s,size_t n){volatile unsigned char *d=p;const volatile unsigned char *b=s;for(size_t i=0;i<n;i++)d[i]=b[i];return p;}
typedef struct { WCHAR path[1024],name[256],service[128],kind[16];USHORT vid,pid,revision,usage_page,usage,input,output,feature;int iface; } Device;
static Device devices[256];static unsigned device_count;
static HWND window,list,status,preview,label_box,start_button,stop_button;
static HFONT font;static HANDLE input=INVALID_HANDLE_VALUE,log_file=INVALID_HANDLE_VALUE,worker,stop_event;
static CRITICAL_SECTION log_lock;static volatile LONG report_count;static DWORD log_bytes,last_error;static ULONGLONG began;static int capture_index=-1;static BOOL active,list_only;
static WCHAR output_root[32768],session_dir[32768],exe_dir[32768],last_dir[32768],current_label[128];static DWORD capture_generation,session_sequence;
static char line[140000];static unsigned line_size;static BYTE report_buffer[65536];static LARGE_INTEGER frequency;
static unsigned length(const WCHAR *s){unsigned n=0;while(s[n])n++;return n;}
static void copy(WCHAR *d,unsigned cap,const WCHAR *s){unsigned n=0;while(s[n]&&n+1<cap){d[n]=s[n];n++;}d[n]=0;}
static BOOL has(const WCHAR *s,const WCHAR *part){for(;*s;s++){const WCHAR *a=s,*b=part;while(*b&&*a==*b){a++;b++;}if(!*b)return TRUE;}return FALSE;}
static int digit(WCHAR c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;return -1;}
static int hex_field(const WCHAR *s,const WCHAR *name){for(;*s;s++){const WCHAR *a=s,*b=name;while(*b&&*a==*b){a++;b++;}if(!*b){int v=0;for(int i=0;i<4;i++){int d=digit(a[i]);if(d<0)return -1;v=v*16+d;}return v;}}return -1;}
static void begin_line(void){line_size=0;}
static void out(const char *s){while(*s&&line_size+1<sizeof(line))line[line_size++]=*s++;line[line_size]=0;}
static void num(ULONGLONG n){char b[24];unsigned i=0;do{b[i++]=(char)('0'+n%10);n/=10;}while(n);while(i){char c[2]={b[--i],0};out(c);}}
static void json_text(const WCHAR *s){
    static char utf8[4096];int n=WideCharToMultiByte(CP_UTF8,0,s,-1,utf8,sizeof(utf8),0,0);out("\"");
    for(int i=0;i<n-1;i++){unsigned char c=(unsigned char)utf8[i];if(c=='"')out("\\\"");else if(c=='\\')out("\\\\");else if(c>=32){char v[2]={(char)c,0};out(v);}}
    out("\"");
}
static BOOL write_line(HANDLE file){DWORD count=0;return WriteFile(file,line,line_size,&count,0)&&count==line_size;}
static void path_join(WCHAR *target,unsigned cap,const WCHAR *folder,const WCHAR *name){copy(target,cap,folder);unsigned n=length(target);if(n+1<cap)target[n++]=L'\\';target[n]=0;copy(target+n,cap-n,name);}
static BOOL in_game_folder(const WCHAR *folder){
    static WCHAR current[32768],test[32768];copy(current,32768,folder);
    for(unsigned depth=0;depth<48;depth++){
        path_join(test,32768,current,L"Sinmai.exe");if(GetFileAttributesW(test)!=INVALID_FILE_ATTRIBUTES)return TRUE;
        path_join(test,32768,current,L"Package\\Sinmai.exe");if(GetFileAttributesW(test)!=INVALID_FILE_ATTRIBUTES)return TRUE;
        unsigned n=length(current);while(n&&current[n-1]!=L'\\'&&current[n-1]!=L'/')n--;if(n<=3)break;current[n-1]=0;
    }
    return FALSE;
}
static HANDLE create_output(const WCHAR *name){static WCHAR path[32768];path_join(path,32768,session_dir,name);return CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);}
static BOOL make_session(void){
    if(in_game_folder(output_root))return FALSE;
    if(!CreateDirectoryW(output_root,0)&&GetLastError()!=ERROR_ALREADY_EXISTS)return FALSE;
    SYSTEMTIME t;GetLocalTime(&t);WCHAR folder[80];
    wsprintfW(folder,L"windows-%04u%02u%02u-%02u%02u%02u-%u-%u",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond,GetCurrentProcessId(),++session_sequence);
    path_join(session_dir,32768,output_root,folder);
    if(!CreateDirectoryW(session_dir,0))return FALSE;
    copy(last_dir,32768,session_dir);return TRUE;
}
static void read_property(HDEVINFO set,SP_DEVINFO_DATA *info,DWORD key,WCHAR *value,DWORD bytes){DWORD type;value[0]=0;SetupDiGetDeviceRegistryPropertyW(set,info,key,&type,(BYTE *)value,bytes,0);value[bytes/sizeof(WCHAR)-1]=0;}
static void enumerate_devices(void){
    device_count=0;
    HDEVINFO usb=SetupDiGetClassDevsW(0,L"USB",0,DIGCF_PRESENT|DIGCF_ALLCLASSES);
    if(usb!=INVALID_HANDLE_VALUE){
        for(DWORD i=0;device_count<128;i++){
            SP_DEVINFO_DATA info={0};info.cbSize=sizeof(info);if(!SetupDiEnumDeviceInfo(usb,i,&info))break;
            static WCHAR hardware[1024];read_property(usb,&info,SPDRP_HARDWAREID,hardware,sizeof(hardware));int vid=hex_field(hardware,L"VID_"),pid=hex_field(hardware,L"PID_");if(vid<0||pid<0)continue;
            Device *d=&devices[device_count++];memset(d,0,sizeof(*d));d->vid=(USHORT)vid;d->pid=(USHORT)pid;d->iface=-1;copy(d->kind,16,L"USB");
            for(const WCHAR *p=hardware;*p;p++)if(p[0]=='M'&&p[1]=='I'&&p[2]=='_'&&digit(p[3])>=0&&digit(p[4])>=0){d->iface=digit(p[3])*16+digit(p[4]);break;}
            read_property(usb,&info,SPDRP_FRIENDLYNAME,d->name,sizeof(d->name));if(!d->name[0])read_property(usb,&info,SPDRP_DEVICEDESC,d->name,sizeof(d->name));
            read_property(usb,&info,SPDRP_SERVICE,d->service,sizeof(d->service));
        }SetupDiDestroyDeviceInfoList(usb);
    }
    GUID guid;HidD_GetHidGuid(&guid);HDEVINFO hid=SetupDiGetClassDevsW(&guid,0,0,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
    if(hid==INVALID_HANDLE_VALUE)return;
    for(DWORD i=0;device_count<256;i++){
        SP_DEVICE_INTERFACE_DATA iface={0};iface.cbSize=sizeof(iface);if(!SetupDiEnumDeviceInterfaces(hid,0,&guid,i,&iface))break;
        static BYTE storage[4096];PSP_DEVICE_INTERFACE_DETAIL_DATA_W detail=(void *)storage;detail->cbSize=sizeof(*detail);SP_DEVINFO_DATA info={0};info.cbSize=sizeof(info);
        if(!SetupDiGetDeviceInterfaceDetailW(hid,&iface,detail,sizeof(storage),0,&info))continue;
        HANDLE h=CreateFileW(detail->DevicePath,0,FILE_SHARE_READ|FILE_SHARE_WRITE,0,OPEN_EXISTING,0,0);
        if(h==INVALID_HANDLE_VALUE)continue;
        HIDD_ATTRIBUTES attributes={0};attributes.Size=sizeof(attributes);PHIDP_PREPARSED_DATA pp=0;HIDP_CAPS caps={0};
        if(!HidD_GetAttributes(h,&attributes)||!HidD_GetPreparsedData(h,&pp)){CloseHandle(h);continue;}
        NTSTATUS rc=HidP_GetCaps(pp,&caps);HidD_FreePreparsedData(pp);if(rc!=HIDP_STATUS_SUCCESS){CloseHandle(h);continue;}
        Device *d=&devices[device_count++];memset(d,0,sizeof(*d));copy(d->kind,16,L"HID");copy(d->path,1024,detail->DevicePath);d->vid=attributes.VendorID;d->pid=attributes.ProductID;d->revision=attributes.VersionNumber;d->usage_page=caps.UsagePage;d->usage=caps.Usage;d->input=caps.InputReportByteLength;d->output=caps.OutputReportByteLength;d->feature=caps.FeatureReportByteLength;d->iface=-1;
        if(!HidD_GetProductString(h,d->name,sizeof(d->name)))read_property(hid,&info,SPDRP_DEVICEDESC,d->name,sizeof(d->name));
        read_property(hid,&info,SPDRP_SERVICE,d->service,sizeof(d->service));CloseHandle(h);
        for(const WCHAR *p=d->path;*p;p++)if((p[0]=='m'||p[0]=='M')&&(p[1]=='i'||p[1]=='I')&&p[2]=='_'&&digit(p[3])>=0&&digit(p[4])>=0){d->iface=digit(p[3])*16+digit(p[4]);break;}
    }SetupDiDestroyDeviceInfoList(hid);
}
static void device_json(unsigned index){
    Device *d=&devices[index];out("{\"index\":");num(index);out(",\"kind\":");json_text(d->kind);out(",\"name\":");json_text(d->name);out(",\"service\":");json_text(d->service);
    out(",\"vid\":");num(d->vid);out(",\"pid\":");num(d->pid);out(",\"revision\":");num(d->revision);out(",\"interface_number\":");if(d->iface<0)out("null");else num((unsigned)d->iface);
    out(",\"usage_page\":");num(d->usage_page);out(",\"usage\":");num(d->usage);out(",\"input_report_bytes\":");num(d->input);out(",\"output_report_bytes\":");num(d->output);out(",\"feature_report_bytes\":");num(d->feature);out("}");
}
static BOOL save_inventory(void){
    HANDLE file=create_output(L"inventory.json");if(file==INVALID_HANDLE_VALUE)return FALSE;
    begin_line();out("{\"format_version\":1,\"physical_hdx_verified\":false,\"hid_output_or_feature_reports_sent\":false,\"runtime\":\"");
    out(GetProcAddress(GetModuleHandleW(L"ntdll.dll"),"wine_get_version")?"Wine":"Windows");out("\",\"devices\":[");BOOL ok=write_line(file);
    for(unsigned i=0;i<device_count&&ok;i++){begin_line();if(i)out(",");device_json(i);ok=write_line(file);}begin_line();out("]}\n");if(ok)ok=write_line(file);CloseHandle(file);return ok;
}
static void refresh_list(void){
    if(active)return;enumerate_devices();SendMessageW(list,LB_RESETCONTENT,0,0);
    for(unsigned i=0;i<device_count;i++){WCHAR row[512];wsprintfW(row,L"[%s] %s   %04X:%04X   Usage %04X:%04X",devices[i].kind,devices[i].name,devices[i].vid,devices[i].pid,devices[i].usage_page,devices[i].usage);SendMessageW(list,LB_ADDSTRING,0,(LPARAM)row);}
    SetWindowTextW(status,L"选择 HDX 对应的 HID 接口，再开始只读采样。USB 行只保存识别信息。");
}
static void save_summary(const char *reason){
    HANDLE file=create_output(L"summary.json");if(file==INVALID_HANDLE_VALUE)return;
    begin_line();out("{\"physical_hdx_verified\":false,\"touch_mapping_verified\":false,\"led_verified\":false,\"logged_reports\":");num((DWORD)report_count);out(",\"last_read_error\":");num(last_error);out(",\"stop_reason\":\"");out(reason);out("\",\"report_id_included_in_windows_read_buffer\":true,\"selected_index\":");num((unsigned)capture_index);out("}\n");write_line(file);CloseHandle(file);
}
static DWORD WINAPI capture_thread(void *unused){
    (void)unused;DWORD generation=capture_generation;OVERLAPPED io={0};io.hEvent=CreateEventW(0,TRUE,FALSE,0);HANDLE waits[2]={stop_event,io.hEvent};last_error=0;
    while(WaitForSingleObject(stop_event,0)!=WAIT_OBJECT_0&&GetTickCount64()-began<60000){
        ResetEvent(io.hEvent);DWORD count=0;BOOL immediate=ReadFile(input,report_buffer,devices[capture_index].input,&count,&io);
        if(!immediate){
            DWORD error=GetLastError();if(error!=ERROR_IO_PENDING){last_error=error;break;}
            DWORD wait=WaitForMultipleObjects(2,waits,FALSE,200);
            if(wait==WAIT_OBJECT_0){CancelIoEx(input,&io);GetOverlappedResult(input,&io,&count,TRUE);break;}
            if(wait==WAIT_TIMEOUT){CancelIoEx(input,&io);GetOverlappedResult(input,&io,&count,TRUE);continue;}
            if(wait!=WAIT_OBJECT_0+1||!GetOverlappedResult(input,&io,&count,FALSE)){last_error=GetLastError();break;}
        }
        if(count){
            EnterCriticalSection(&log_lock);LARGE_INTEGER tick;QueryPerformanceCounter(&tick);begin_line();out("{\"kind\":\"raw_input\",\"seq\":");num((DWORD)report_count+1);out(",\"qpc\":");num((ULONGLONG)tick.QuadPart);out(",\"qpc_frequency\":");num((ULONGLONG)frequency.QuadPart);out(",\"byte_count\":");num(count);out(",\"report_id\":");num(report_buffer[0]);out(",\"action_label\":");json_text(current_label);out(",\"hex\":\"");
            const char *hex="0123456789abcdef";for(DWORD j=0;j<count;j++){char pair[3]={hex[report_buffer[j]>>4],hex[report_buffer[j]&15],0};out(pair);}out("\"}\n");
            if(log_bytes+line_size>8*1024*1024){last_error=ERROR_FILE_TOO_LARGE;LeaveCriticalSection(&log_lock);break;}
            if(!write_line(log_file)){last_error=GetLastError();LeaveCriticalSection(&log_lock);break;}log_bytes+=line_size;InterlockedIncrement(&report_count);LeaveCriticalSection(&log_lock);
        }
    }
    CloseHandle(io.hEvent);PostMessageW(window,WM_APP+1,generation,0);return 0;
}
static void stop_capture(const char *reason){
    if(!active)return;SetEvent(stop_event);CancelIoEx(input,0);
    if(WaitForSingleObject(worker,3000)!=WAIT_OBJECT_0){SetWindowTextW(status,L"正在等待设备取消读取，句柄仍保留。请稍候再关闭窗口。");return;}
    CloseHandle(worker);CloseHandle(stop_event);CloseHandle(input);input=INVALID_HANDLE_VALUE;FlushFileBuffers(log_file);CloseHandle(log_file);log_file=INVALID_HANDLE_VALUE;active=FALSE;save_summary(reason);
    EnableWindow(start_button,TRUE);EnableWindow(stop_button,FALSE);EnableWindow(list,TRUE);SetWindowTextW(status,L"记录已保存。收到报告不代表触摸映射或灯光已验证。");
}
static void start_capture(void){
    if(active)return;LRESULT selected=SendMessageW(list,LB_GETCURSEL,0,0);
    if(selected<0||(unsigned)selected>=device_count||!devices[selected].input){MessageBoxW(window,L"请选择带输入报告的 HID 接口。串口和厂商管道本轮只识别。",L"选择输入接口",MB_OK|MB_ICONINFORMATION);return;}
    if(!make_session()){MessageBoxW(window,L"无法创建记录目录。请将工具放在游戏 HDD 以外的可写文件夹。",L"记录目录不可用",MB_OK|MB_ICONERROR);return;}
    if(!save_inventory()){SetWindowTextW(status,L"无法保存识别信息，未开始设备采样。");return;}capture_index=(int)selected;
    input=CreateFileW(devices[selected].path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,0,OPEN_EXISTING,FILE_FLAG_OVERLAPPED,0);
    if(input==INVALID_HANDLE_VALUE){last_error=GetLastError();report_count=0;save_summary("device_open_failed");MessageBoxW(window,L"无法只读打开此接口。请检查是否被其他程序独占；识别信息已保存。",L"设备尚不可读",MB_OK|MB_ICONWARNING);return;}
    log_file=create_output(L"input-reports.jsonl");if(log_file==INVALID_HANDLE_VALUE){CloseHandle(input);input=INVALID_HANDLE_VALUE;return;}
    report_count=0;log_bytes=0;began=GetTickCount64();stop_event=CreateEventW(0,TRUE,FALSE,0);capture_generation++;active=TRUE;worker=CreateThread(0,0,capture_thread,0,0,0);
    if(!worker){active=FALSE;CloseHandle(stop_event);CloseHandle(input);CloseHandle(log_file);return;}
    EnableWindow(start_button,FALSE);EnableWindow(stop_button,TRUE);EnableWindow(list,FALSE);SetWindowTextW(status,L"只读采样中，最长 60 秒。请按测试项目操作 HDX。");
}
static HWND control(const WCHAR *cls,const WCHAR *title,DWORD style,int x,int y,int w,int h,int id){HWND result=CreateWindowW(cls,title,WS_CHILD|WS_VISIBLE|style,x,y,w,h,window,(HMENU)(INT_PTR)id,GetModuleHandleW(0),0);SendMessageW(result,WM_SETFONT,(WPARAM)font,TRUE);return result;}
static LRESULT CALLBACK procedure(HWND h,UINT message,WPARAM w,LPARAM l){
    switch(message){
    case WM_CREATE:
        window=h;font=CreateFontW(-17,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,DEFAULT_QUALITY,DEFAULT_PITCH,L"Segoe UI");
        control(L"STATIC",L"HDX 接线测试 · Windows / Wine 对照",0,20,16,760,30,0);
        control(L"STATIC",L"仅识别接口、只读采集选定 HID。不会写灯光、更新固件或启动游戏。",0,20,50,820,28,0);
        list=control(L"LISTBOX",L"",WS_BORDER|WS_VSCROLL|LBS_NOTIFY,20,90,820,300,10);
        control(L"BUTTON",L"刷新设备",0,20,410,130,38,11);start_button=control(L"BUTTON",L"开始只读采样",0,164,410,180,38,12);stop_button=control(L"BUTTON",L"结束并保存",0,358,410,160,38,13);EnableWindow(stop_button,FALSE);
        control(L"BUTTON",L"打开记录文件夹",0,532,410,180,38,14);control(L"BUTTON",L"保存识别信息",0,20,460,160,38,15);
        label_box=control(L"COMBOBOX",L"",CBS_DROPDOWNLIST|WS_VSCROLL,200,460,220,240,16);
        const WCHAR *labels[]={L"未标记",L"外键 1",L"外键 2",L"外键 3",L"外键 4",L"外键 5",L"外键 6",L"外键 7",L"外键 8",L"功能键",L"单点触摸",L"多点触摸",L"长触",L"全部释放"};
        for(unsigned i=0;i<sizeof(labels)/sizeof(labels[0]);i++)SendMessageW(label_box,CB_ADDSTRING,0,(LPARAM)labels[i]);SendMessageW(label_box,CB_SETCURSEL,0,0);copy(current_label,128,L"未标记");
        status=control(L"STATIC",L"",0,20,516,820,48,0);preview=control(L"STATIC",L"实体 HDX 未验证。请与 Mac 使用同一设备、固件和操作顺序。",0,20,572,820,44,0);
        SetTimer(h,1,250,0);refresh_list();return 0;
    case WM_COMMAND:
        if(LOWORD(w)==11)refresh_list();else if(LOWORD(w)==12)start_capture();else if(LOWORD(w)==13)stop_capture("operator_stop");
        else if(LOWORD(w)==14&&last_dir[0]){STARTUPINFOW si={0};PROCESS_INFORMATION pi={0};static WCHAR command[32800];si.cb=sizeof(si);copy(command,32800,L"explorer.exe \"");unsigned n=length(command);copy(command+n,32800-n,last_dir);n=length(command);copy(command+n,32800-n,L"\"");if(CreateProcessW(0,command,0,0,FALSE,0,0,0,&si,&pi)){CloseHandle(pi.hProcess);CloseHandle(pi.hThread);}}
        else if(LOWORD(w)==15&&!active){if(make_session()){SetWindowTextW(status,save_inventory()?L"识别信息已保存；未开始设备输入采样。":L"识别信息无法保存，请检查文件夹权限和剩余空间。");}}
        else if(LOWORD(w)==16&&HIWORD(w)==CBN_SELCHANGE){WCHAR value[128];GetWindowTextW(label_box,value,128);EnterCriticalSection(&log_lock);copy(current_label,128,value);LeaveCriticalSection(&log_lock);}return 0;
    case WM_TIMER:if(active){WCHAR text[256];DWORD elapsed=(DWORD)((GetTickCount64()-began)/1000);wsprintfW(text,L"已记录 %u 条输入报告 · 剩余 %u 秒 · 原始数据未作 HDX 协议推断",(DWORD)report_count,elapsed>=60?0:60-elapsed);SetWindowTextW(preview,text);}return 0;
    case WM_APP+1:if((DWORD)w==capture_generation)stop_capture(last_error?"read_error_or_recording_limit":"60_second_limit");return 0;
    case WM_CLOSE:stop_capture("window_closed");if(!active)DestroyWindow(h);return 0;
    case WM_DESTROY:PostQuitMessage(0);return 0;
    default:return DefWindowProcW(h,message,w,l);
    }
}
void WinMainCRTStartup(void){
    SetProcessDPIAware();InitializeCriticalSection(&log_lock);QueryPerformanceFrequency(&frequency);
    GetModuleFileNameW(0,exe_dir,32768);unsigned n=length(exe_dir);while(n&&exe_dir[n-1]!=L'\\'&&exe_dir[n-1]!=L'/')n--;if(n)exe_dir[n-1]=0;
    if(!GetEnvironmentVariableW(L"AIRMAIDX_HDX_OUTPUT",output_root,32768))path_join(output_root,32768,exe_dir,L"记录");
    list_only=has(GetCommandLineW(),L"--list-only");
    if(list_only){enumerate_devices();if(!make_session())ExitProcess(2);ExitProcess(save_inventory()?0:3);}
    WNDCLASSW cls={0};cls.lpfnWndProc=procedure;cls.hInstance=GetModuleHandleW(0);cls.lpszClassName=L"AirmaiDXHDXProbe";cls.hCursor=LoadCursorW(0,IDC_ARROW);cls.hbrBackground=(HBRUSH)(COLOR_WINDOW+1);RegisterClassW(&cls);
    window=CreateWindowW(cls.lpszClassName,L"HDX 接线测试",WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU|WS_MINIMIZEBOX,CW_USEDEFAULT,CW_USEDEFAULT,880,680,0,0,cls.hInstance,0);
    ShowWindow(window,SW_SHOW);UpdateWindow(window);MSG message;while(GetMessageW(&message,0,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}DeleteCriticalSection(&log_lock);ExitProcess(0);
}
