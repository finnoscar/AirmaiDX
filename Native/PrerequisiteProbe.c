#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <ws2tcpip.h>
void *memcpy(void *dst,const void *src,size_t n) {
    volatile unsigned char *d=(volatile unsigned char *)dst;
    const volatile unsigned char *s=(const volatile unsigned char *)src;
    for(size_t i=0;i<n;i++)d[i]=s[i];return dst;
}

/* Freestanding, self-authored PE. No game code, CRT, installer, or HTTP client.
   Network test connects only to a parent-owned 127.0.0.1 test listener. */
static void text(const char *s) {
    DWORD n=0,w=0;while(s[n])n++;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,n,&w,0);
}
static void number(DWORD n) {
    char buf[16];unsigned i=0;do {buf[i++]=(char)('0'+n%10);n/=10;} while(n);
    while(i){char one[2]={buf[--i],0};text(one);}
}
static void result(const char *name,DWORD value,DWORD error) {
    text("{\"test\":\"");text(name);text("\",\"value\":");number(value);text(",\"error\":");number(error);text("}\n");
}
static int contains(const WCHAR *s,const WCHAR *needle) {
    for(;*s;s++){const WCHAR *a=s,*b=needle;while(*b && *a==*b){a++;b++;}if(!*b)return 1;}return 0;
}
static WCHAR path[32768];
static WCHAR executable[32768],childcmd[32780];
static void file_check(const WCHAR *env,const char *name,DWORD access,DWORD disposition) {
    if(!GetEnvironmentVariableW(env,path,32768)){result(name,0,GetLastError());return;}
    SetLastError(0);HANDLE h=CreateFileW(path,access,FILE_SHARE_READ|FILE_SHARE_WRITE,0,disposition,FILE_ATTRIBUTE_NORMAL,0);
    DWORD e=GetLastError();result(name,h!=INVALID_HANDLE_VALUE,e);
    if(h!=INVALID_HANDLE_VALUE)CloseHandle(h);
}
static void socket_check(void) {
    WSADATA data;int rc=WSAStartup(MAKEWORD(2,2),&data);
    if(rc){result("loopback_connect",0,(DWORD)rc);return;}
    WCHAR port[16];GetEnvironmentVariableW(L"AIRMAIDX_LOOPBACK_PORT",port,16);
    unsigned p=0;for(unsigned i=0;port[i]>='0'&&port[i]<='9';i++)p=p*10+(port[i]-'0');
    SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
    if(s==INVALID_SOCKET){result("loopback_connect",0,(DWORD)WSAGetLastError());WSACleanup();return;}
    struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_port=htons((u_short)p);addr.sin_addr.s_addr=htonl(0x7f000001);
    rc=connect(s,(const struct sockaddr *)&addr,sizeof(addr));result("loopback_connect",rc==0,rc==0?0:(DWORD)WSAGetLastError());
    closesocket(s);WSACleanup();
}
static void module_check(const WCHAR *name,const char *label) {
    SetLastError(0);HMODULE h=LoadLibraryW(name);result(label,h!=0,GetLastError());if(h)FreeLibrary(h);
}
static void munet_network_test(void) {
    WSADATA data;
    int start=WSAStartup(MAKEWORD(2,2),&data);
    if(start){result("munet_wsa_startup",0,(DWORD)start);return;}
    const char *hosts[]={"play.mumur.net","aime.mumur.net","203.0.113.1"};
    const char *labels[]={"munet_play_tcp443","munet_aime_tcp443","other_destination_must_be_denied"};
    for(unsigned i=0;i<3;i++){
        struct addrinfo hints={0},*resolved=0;hints.ai_family=AF_INET;hints.ai_socktype=SOCK_STREAM;
        int e=getaddrinfo(hosts[i],"443",&hints,&resolved);
        if(e){result(labels[i],0,(DWORD)e);continue;}
        SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);u_long nonblocking=1;ioctlsocket(s,FIONBIO,&nonblocking);
        int rc=connect(s,resolved->ai_addr,(int)resolved->ai_addrlen),error=rc?WSAGetLastError():0;
        if(rc && error==WSAEWOULDBLOCK){
            fd_set write_set,except_set;FD_ZERO(&write_set);FD_ZERO(&except_set);FD_SET(s,&write_set);FD_SET(s,&except_set);
            struct timeval timeout={8,0};int n=select(0,0,&write_set,&except_set,&timeout);
            int len=sizeof(error);if(n>0)getsockopt(s,SOL_SOCKET,SO_ERROR,(char *)&error,&len);else error=WSAETIMEDOUT;
        }
        result(labels[i],error==0,(DWORD)error);closesocket(s);freeaddrinfo(resolved);
    }
    WSACleanup();
}
static void munet_http_test(void) {
    WSADATA data;if(WSAStartup(MAKEWORD(2,2),&data))return;
    WCHAR select_text[16];BOOL select_test=GetEnvironmentVariableW(L"AIRMAIDX_HTTP_SELECT_TEST",select_text,16)!=0;
    const char *hosts[]={"play.mumur.net","aime.mumur.net"};
    const char *requests[]={"HEAD / HTTP/1.1\r\nHost: play.mumur.net\r\nConnection: close\r\n\r\n","HEAD / HTTP/1.1\r\nHost: aime.mumur.net\r\nConnection: close\r\n\r\n"};
    const char *labels[]={"munet_play_http_status","munet_aime_http_status"};
    for(unsigned i=0;i<2;i++){
        struct addrinfo hints={0},*resolved=0;hints.ai_family=AF_INET;hints.ai_socktype=SOCK_STREAM;
        int e=getaddrinfo(hosts[i],"80",&hints,&resolved);if(e){result(labels[i],0,(DWORD)e);continue;}
        SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);DWORD timeout=8000;
        setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(const char *)&timeout,sizeof(timeout));
        setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,(const char *)&timeout,sizeof(timeout));
        int rc=connect(s,resolved->ai_addr,(int)resolved->ai_addrlen);
        if(rc){result(labels[i],0,(DWORD)WSAGetLastError());closesocket(s);freeaddrinfo(resolved);continue;}
        int len=0;while(requests[i][len])len++;
        if(select_test){u_long mode=1;ioctlsocket(s,FIONBIO,&mode);}
        rc=send(s,requests[i],len,0);
        if(select_test && rc>0){
            fd_set read_set;FD_ZERO(&read_set);FD_SET(s,&read_set);struct timeval read_timeout={8,0};DWORD began=GetTickCount();
            int selected=select(0,&read_set,0,0,&read_timeout);
            result("munet_nonblocking_select_result",selected<0?0:(DWORD)selected,GetTickCount()-began);
            u_long pending=0;ioctlsocket(s,FIONREAD,&pending);result("munet_nonblocking_pending_bytes",pending,0);
        }
        static char response[4096];int count=rc>0?recv(s,response,sizeof(response),0):-1;
        DWORD status=0;
        if(count>=12 && response[0]=='H' && response[9]>='0' && response[9]<='9')
            status=(response[9]-'0')*100+(response[10]-'0')*10+response[11]-'0';
        result(labels[i],status,count<0?(DWORD)WSAGetLastError():0);
        closesocket(s);freeaddrinfo(resolved);
    }
    WSACleanup();
}
static void launch_game(void) {
    static WCHAR command[4096];
    const WCHAR default_command[]=L"Sinmai.exe -force-d3d11 -screen-fullscreen 0 -screen-width 720 -screen-height 1280 -logFile C:\\AirmaiDX\\airmaidx-player.log";
    if(!GetEnvironmentVariableW(L"AIRMAIDX_GAME_COMMAND",command,4096)){
        unsigned i=0;do{command[i]=default_command[i];}while(default_command[i++]);
    }
    STARTUPINFOW si={0};PROCESS_INFORMATION pi={0};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES;
    WCHAR show_window[16];
    if(GetEnvironmentVariableW(L"AIRMAIDX_SHOW_GAME_WINDOW",show_window,16)){
        si.dwFlags|=STARTF_USESHOWWINDOW;si.wShowWindow=SW_SHOWNORMAL;
    }
    si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    BOOL made=CreateProcessW(L"Sinmai.exe",command,0,0,TRUE,0,0,0,&si,&pi);result("sinmai_created",made,made?0:GetLastError());
    if(!made)return;
    result("sinmai_windows_pid",pi.dwProcessId,0);
    WCHAR wait_text[16];DWORD duration=45000;
    if(GetEnvironmentVariableW(L"AIRMAIDX_GAME_WAIT_MS",wait_text,16)){
        DWORD n=0;for(unsigned j=0;wait_text[j]>='0'&&wait_text[j]<='9';j++)n=n*10+(wait_text[j]-'0');
        if(n>=1000&&n<=21600000)duration=n;
    }
    if(GetEnvironmentVariableW(L"AIRMAIDX_KEEP_GAME_OPEN",wait_text,16))duration=INFINITE;
    DWORD wait=WaitForSingleObject(pi.hProcess,duration),code=0;GetExitCodeProcess(pi.hProcess,&code);result("sinmai_wait",wait,code);
    if(wait==WAIT_TIMEOUT){TerminateProcess(pi.hProcess,110);WaitForSingleObject(pi.hProcess,3000);result("sinmai_stopped_by_test_timeout",1,0);}
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
}
static void api_test(void) {
    if(GetEnvironmentVariableW(L"AIRMAIDX_WORKDIR",path,32768)){
        BOOL changed=SetCurrentDirectoryW(path);result("windows_workdir_set",changed,changed?0:GetLastError());
    }
    WCHAR command[512];
    static const WCHAR normal_command[]=L"inject.exe -d -k mai2hook.dll amdaemon.exe -f -c config_common.json config_server.json config_client.json";
    static const WCHAR observed_command[]=L"inject.exe -d -k C:\\AirmaiNetworkObserveOrdinal.dll -k mai2hook.dll amdaemon.exe -f -c config_common.json config_server.json config_client.json";
    static const WCHAR fixed_command[]=L"inject.exe -d -k C:\\AirmaiNetworkObserveOrdinal.dll -k C:\\AirmaiMunetRelay.dll -k C:\\AirmaiMunetFinCompat.dll -k mai2hook.dll amdaemon.exe -f -c config_common.json config_server.json config_client.json";
    WCHAR trace[8];const WCHAR *chosen=GetEnvironmentVariableW(L"AIRMAIDX_TRACE_DAEMON_NETWORK",trace,8)?observed_command:normal_command;
    if(GetEnvironmentVariableW(L"AIRMAIDX_MUNET_NETWORK_FIX",trace,8))chosen=fixed_command;
    unsigned ci=0;do{command[ci]=chosen[ci];}while(chosen[ci++]);
    STARTUPINFOW si={0};PROCESS_INFORMATION pi={0};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES;
    si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    BOOL made=CreateProcessW(L"inject.exe",command,0,0,TRUE,0,0,0,&si,&pi);result("injector_created",made,made?0:GetLastError());
    if(!made)return;
    Sleep(2000);
    DWORD exit=0;GetExitCodeProcess(pi.hProcess,&exit);result("injector_initial_exit_code",exit,0);
    WCHAR skip[16];
    if(GetEnvironmentVariableW(L"AIRMAIDX_SKIP_API_PRECHECK",skip,16)){
        result("api_precheck_skipped_original_chain",1,0);
        launch_game();CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return;
    }
    if(!GetEnvironmentVariableW(L"AIRMAIDX_API_DLL",path,32768))return;
    HMODULE lib=LoadLibraryW(path);result("amdaemon_api_loaded",lib!=0,lib?0:GetLastError());
    if(lib){
        typedef void (*execute_fn)(void);typedef unsigned char (*ready_fn)(void);
        execute_fn execute=(execute_fn)(void *)GetProcAddress(lib,"Core_execute");ready_fn ready=(ready_fn)(void *)GetProcAddress(lib,"Core_isReady");
        result("core_functions_found",execute&&ready,0);
        if(execute&&ready){
            typedef void (*register_fn)(void);
            register_fn register_hook=(register_fn)(void *)GetProcAddress(lib,"Core_setExceptionHook_register");
            if(register_hook){register_hook();result("exception_hook_registered_like_managed_api_cctor",1,0);}
            result("before_core_execute",1,0);execute();result("after_core_execute",1,0);
            DWORD observed=0,first=GetTickCount();
            while(GetTickCount()-first<15000){execute();if(ready()){observed=1;break;}Sleep(100);}
            result("amdaemon_core_ready",observed,GetTickCount()-first);
            WCHAR status_mode[16];
            if(observed && GetEnvironmentVariableW(L"AIRMAIDX_AM_STATUS_PROBE",status_mode,16)){
                typedef int (*players_fn)(void);typedef void *(*info_fn)(void);
                typedef unsigned char (*occurred_fn)(void *);typedef int (*number_fn)(void *);
                players_fn players=(players_fn)(void *)GetProcAddress(lib,"Core_getPlayerCount");
                info_fn info=(info_fn)(void *)GetProcAddress(lib,"Error_getInfo");
                occurred_fn occurred=(occurred_fn)(void *)GetProcAddress(lib,"ErrorInfo_isOccurred");
                number_fn num=(number_fn)(void *)GetProcAddress(lib,"ErrorInfo_getNumber");
                number_fn sub=(number_fn)(void *)GetProcAddress(lib,"ErrorInfo_getSubNumber");
                for(unsigned i=0;i<30;i++){execute();Sleep(100);}
                if(players)result("amdaemon_player_count",(DWORD)players(),0);
                void *err=info?info():0;result("amdaemon_error_info_present",err!=0,0);
                if(err&&occurred&&num&&sub){result("amdaemon_error_occurred",occurred(err),0);result("amdaemon_error_number",(DWORD)num(err),(DWORD)sub(err));}
            }
            WCHAR seq_mode[16];
            if(GetEnvironmentVariableW(L"AIRMAIDX_SEQUENCE_PROBE",seq_mode,16)){
                typedef unsigned char (*sequence_fn)(int);
                typedef unsigned (*count_fn)(void);
                typedef void *(*check_fn)(void);
                sequence_fn seq=(sequence_fn)(void *)GetProcAddress(lib,"Sequence_isPlaying");
                count_fn count=(count_fn)(void *)GetProcAddress(lib,"Core_setExceptionHook_count");
                check_fn check=(check_fn)(void *)GetProcAddress(lib,"Core_setExceptionHook_check");
                result("sequence_probe_exports",seq&&count&&check,0);
                if(seq&&count&&check){
                    result("exception_queue_before",count(),0);
                    result("sequence_is_playing",seq(0),0);
                    unsigned n=count();result("exception_queue_after",n,0);
                    if(n){result("before_exception_queue_check",1,0);void *ex=check();result("exception_queue_check_returned",ex!=0,0);}
                }
            }
            WCHAR game_mode[16];
            if(observed && GetEnvironmentVariableW(L"AIRMAIDX_LAUNCH_GAME",game_mode,16)){
                launch_game();
            }
        }
        /* Let process exit close this native API. Its worker lifetime is not yet established. */
    }
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
}
static void graphics_test(void) {
    HMODULE nt=GetModuleHandleW(L"ntdll.dll");
    result("ntdll_unix_dispatcher_export",GetProcAddress(nt,"__wine_unix_call_dispatcher")!=0,0);
    result("ntdll_unix_call_export",GetProcAddress(nt,"__wine_unix_call")!=0,0);
    HMODULE lib=LoadLibraryW(L"d3d11.dll");result("d3d11_module",lib!=0,lib?0:GetLastError());
    if(!lib)return;
    typedef LONG (WINAPI *create_fn)(void *,unsigned,HMODULE,unsigned,const unsigned *,unsigned,unsigned,void **,unsigned *,void **);
    create_fn create=(create_fn)(void *)GetProcAddress(lib,"D3D11CreateDevice");result("d3d11_create_export",create!=0,create?0:GetLastError());
    if(create){void *device=0,*context=0;unsigned level=0,requested=0xb000;LONG hr=create(0,1,0,0,&requested,1,7,&device,&level,&context);result("d3d11_level11_create_hresult",(DWORD)hr,0);result("d3d11_level11_device_created",device!=0,level);}
}
void mainCRTStartup(void) {
    if(contains(GetCommandLineW(),L"--munet-http")){munet_http_test();ExitProcess(0);}
    if(contains(GetCommandLineW(),L"--munet-network")){munet_network_test();ExitProcess(0);}
    if(contains(GetCommandLineW(),L"--launch-daemon")){api_test();ExitProcess(0);}
    if(contains(GetCommandLineW(),L"--graphics")){graphics_test();ExitProcess(0);}
    int child=contains(GetCommandLineW(),L"--child");
    result(child?"child_started":"parent_started",1,0);
    file_check(L"AIRMAIDX_ALLOWED_FILE","allowed_read",GENERIC_READ,OPEN_EXISTING);
    file_check(L"AIRMAIDX_SOURCE_FILE","source_read",GENERIC_READ,OPEN_EXISTING);
    file_check(L"AIRMAIDX_DENIED_WRITE_FILE","denied_write_open",GENERIC_WRITE,OPEN_EXISTING);
    file_check(L"AIRMAIDX_ALLOWED_FILE","allowed_write_open",GENERIC_WRITE,OPEN_EXISTING);
    socket_check();
    HANDLE map=child?OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,L"Local\\AirmaiDXLabProbe"):
        CreateFileMappingW(INVALID_HANDLE_VALUE,0,PAGE_READWRITE,0,4096,L"Local\\AirmaiDXLabProbe");
    volatile DWORD *view=map?(volatile DWORD *)MapViewOfFile(map,FILE_MAP_ALL_ACCESS,0,0,4096):0;
    if(child){
        result("child_mapping_cookie",view&&view[0]==0x4149524d,GetLastError());
        if(view)view[1]=0x44584f4b;
    } else if(view) {
        view[0]=0x4149524d;view[1]=0;
        WCHAR *exe=executable,*cmd=childcmd;DWORD len=GetModuleFileNameW(0,exe,32768),i=0;
        cmd[i++]='"';for(DWORD j=0;j<len;j++)cmd[i++]=exe[j];cmd[i++]='"';
        const WCHAR suffix[]=L" --child";for(unsigned j=0;suffix[j];j++)cmd[i++]=suffix[j];cmd[i]=0;
        STARTUPINFOW si={0};PROCESS_INFORMATION pi={0};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES;
        si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);
        BOOL ok=CreateProcessW(exe,cmd,0,0,TRUE,0,0,0,&si,&pi);result("child_created",ok,GetLastError());
        if(ok){DWORD wait=WaitForSingleObject(pi.hProcess,10000),exit=0;GetExitCodeProcess(pi.hProcess,&exit);result("child_wait",wait,exit);if(wait==WAIT_TIMEOUT)TerminateProcess(pi.hProcess,99);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);}
        result("parent_mapping_reply",view[1]==0x44584f4b,0);
        module_check(L"msvcr110.dll","load_msvcr110");module_check(L"msvcp110.dll","load_msvcp110");
        module_check(L"vcruntime140.dll","load_vcruntime140");module_check(L"vcruntime140_1.dll","load_vcruntime140_1");
        module_check(L"msvcp140.dll","load_msvcp140");module_check(L"mfplat.dll","load_mfplat");
    } else result("mapping_created",0,GetLastError());
    if(view)UnmapViewOfFile((const void *)view);if(map)CloseHandle(map);
    ExitProcess(0);
}
