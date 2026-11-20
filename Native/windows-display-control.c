/* Owned game window geometry helper. Default is read-only inventory.
 * Preview mode changes only the one verified Sinmai Unity window, restores
 * its style/placement after 20 seconds, and never changes a display mode. */
#define WinMainCRTStartup unused_kit_ui_entry
#include "windows-hid-probe.c"
#undef WinMainCRTStartup
static HWND game_hwnd;static DWORD game_pid;static unsigned game_count,monitor_count;
static MONITORINFOEXW monitors[16];
typedef struct {DWORD magic,version,pid;HWND hwnd;LONG_PTR style,exstyle;WINDOWPLACEMENT placement;RECT rect;} RestorePoint;
static RestorePoint restore_point;
static void signed_num(LONG n){if(n<0){out("-");num((ULONGLONG)(-(LONGLONG)n));}else num((DWORD)n);}
static void rect_json(RECT r){out("{\"left\":");signed_num(r.left);out(",\"top\":");signed_num(r.top);out(",\"right\":");signed_num(r.right);out(",\"bottom\":");signed_num(r.bottom);out("}");}
static BOOL CALLBACK find_game(HWND h,LPARAM unused){
    (void)unused;WCHAR cls[128],title[128];GetClassNameW(h,cls,128);GetWindowTextW(h,title,128);
    if(lstrcmpW(cls,L"UnityWndClass")||lstrcmpW(title,L"Sinmai"))return TRUE;
    DWORD pid=0;GetWindowThreadProcessId(h,&pid);HANDLE p=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);
    if(!p)return TRUE;
    static WCHAR path[32768];DWORD n=32768;BOOL ok=QueryFullProcessImageNameW(p,0,path,&n);CloseHandle(p);
    if(!ok)return TRUE;const WCHAR *base=path;for(const WCHAR *c=path;*c;c++)if(*c=='\\'||*c=='/')base=c+1;
    if(lstrcmpiW(base,L"Sinmai.exe"))return TRUE;
    game_hwnd=h;game_pid=pid;game_count++;return TRUE;
}
static BOOL CALLBACK find_monitor(HMONITOR h,HDC dc,LPRECT r,LPARAM unused){
    (void)dc;(void)r;(void)unused;if(monitor_count>=16)return FALSE;
    MONITORINFOEXW *m=&monitors[monitor_count];m->cbSize=sizeof(*m);
    if(GetMonitorInfoW(h,(MONITORINFO *)m))monitor_count++;
    return TRUE;
}
static void save(const char *phase,BOOL changed){
    HANDLE f=CreateFileW(L"C:\\AirmaiDisplay-control.json",GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    if(f==INVALID_HANDLE_VALUE)return;
    begin_line();out("{\"phase\":\"");out(phase);out("\",\"display_mode_changed\":false,\"window_changed\":");out(changed?"true":"false");
    out(",\"game_window_count\":");num(game_count);out(",\"windows_game_pid\":");num(game_pid);out(",\"hwnd\":");num((ULONG_PTR)game_hwnd);
    out(",\"window\":");RECT wr={0},cr={0};GetWindowRect(game_hwnd,&wr);GetClientRect(game_hwnd,&cr);rect_json(wr);out(",\"client\":");rect_json(cr);
    out(",\"style\":");num((ULONG_PTR)GetWindowLongPtrW(game_hwnd,GWL_STYLE));out(",\"exstyle\":");num((ULONG_PTR)GetWindowLongPtrW(game_hwnd,GWL_EXSTYLE));
    typedef UINT (WINAPI *DpiFn)(HWND);DpiFn dpi=(DpiFn)(void *)GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetDpiForWindow");
    out(",\"window_dpi\":");num(dpi?dpi(game_hwnd):0);out(",\"monitors\":[");
    for(unsigned i=0;i<monitor_count;i++){
        MONITORINFOEXW *m=&monitors[i];if(i)out(",");out("{\"index\":");num(i);out(",\"device\":");json_text(m->szDevice);
        out(",\"primary\":");out(m->dwFlags&MONITORINFOF_PRIMARY?"true":"false");out(",\"bounds\":");rect_json(m->rcMonitor);out(",\"work\":");rect_json(m->rcWork);
        DEVMODEW mode={0};mode.dmSize=sizeof(mode);if(EnumDisplaySettingsW(m->szDevice,ENUM_CURRENT_SETTINGS,&mode)){
            out(",\"current_width\":");num(mode.dmPelsWidth);out(",\"current_height\":");num(mode.dmPelsHeight);out(",\"refresh_hz\":");num(mode.dmDisplayFrequency);
        }out("}");
    }out("]}\n");write_line(f);CloseHandle(f);
}
void WinMainCRTStartup(void){
    SetProcessDPIAware();EnumWindows(find_game,0);EnumDisplayMonitors(0,0,find_monitor,0);save("query",FALSE);
    if(game_count!=1)ExitProcess(2);
    WCHAR action[32];if(!GetEnvironmentVariableW(L"AIRMAIDX_DISPLAY_ACTION",action,32))ExitProcess(0);
    BOOL preview=!lstrcmpW(action,L"preview"),apply=!lstrcmpW(action,L"apply"),restore=!lstrcmpW(action,L"restore");
    if(!preview&&!apply&&!restore)ExitProcess(3);
    if(restore){
        HANDLE file=CreateFileW(L"C:\\AirmaiDisplay-restore.bin",GENERIC_READ,FILE_SHARE_READ,0,OPEN_EXISTING,0,0);DWORD got=0;
        if(file==INVALID_HANDLE_VALUE)ExitProcess(7);
        BOOL ok=ReadFile(file,&restore_point,sizeof(restore_point),&got,0);CloseHandle(file);
        if(!ok||got!=sizeof(restore_point)||restore_point.magic!=0x41445031||restore_point.version!=1||restore_point.pid!=game_pid||restore_point.hwnd!=game_hwnd)ExitProcess(8);
        SetWindowLongPtrW(game_hwnd,GWL_STYLE,restore_point.style);SetWindowLongPtrW(game_hwnd,GWL_EXSTYLE,restore_point.exstyle);
        SetWindowPlacement(game_hwnd,&restore_point.placement);RECT r=restore_point.rect;
        SetWindowPos(game_hwnd,HWND_NOTOPMOST,r.left,r.top,r.right-r.left,r.bottom-r.top,SWP_FRAMECHANGED|SWP_ASYNCWINDOWPOS|SWP_NOOWNERZORDER);
        Sleep(500);save("restored_from_independent_helper",FALSE);ExitProcess(0);
    }
    WCHAR target[16];if(!GetEnvironmentVariableW(L"AIRMAIDX_DISPLAY_MONITOR",target,16))ExitProcess(3);
    unsigned index=0;for(WCHAR *c=target;*c;c++){if(*c<'0'||*c>'9')ExitProcess(3);index=index*10+(unsigned)(*c-'0');if(index>=16)ExitProcess(3);}
    if(index>=monitor_count)ExitProcess(3);
    DWORD_PTR response=0;if(!SendMessageTimeoutW(game_hwnd,WM_NULL,0,0,SMTO_ABORTIFHUNG|SMTO_BLOCK,1000,&response))ExitProcess(4);
    WINDOWPLACEMENT before={0};before.length=sizeof(before);if(!GetWindowPlacement(game_hwnd,&before))ExitProcess(5);
    RECT old_rect;GetWindowRect(game_hwnd,&old_rect);LONG_PTR style=GetWindowLongPtrW(game_hwnd,GWL_STYLE),ex=GetWindowLongPtrW(game_hwnd,GWL_EXSTYLE);
    if(apply||preview){
        restore_point.magic=0x41445031;restore_point.version=1;restore_point.pid=game_pid;restore_point.hwnd=game_hwnd;
        restore_point.style=style;restore_point.exstyle=ex;restore_point.placement=before;restore_point.rect=old_rect;
        HANDLE file=CreateFileW(L"C:\\AirmaiDisplay-restore.bin",GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);DWORD written=0;
        if(file==INVALID_HANDLE_VALUE)ExitProcess(9);
        BOOL ok=WriteFile(file,&restore_point,sizeof(restore_point),&written,0);CloseHandle(file);
        if(!ok||written!=sizeof(restore_point))ExitProcess(9);
    }
    LONG_PTR borderless=(style&~(WS_CAPTION|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX|WS_SYSMENU))|WS_POPUP;
    SetWindowLongPtrW(game_hwnd,GWL_STYLE,borderless);SetWindowLongPtrW(game_hwnd,GWL_EXSTYLE,ex&~(WS_EX_DLGMODALFRAME|WS_EX_WINDOWEDGE|WS_EX_CLIENTEDGE));
    RECT r=monitors[index].rcMonitor;
    BOOL applied=SetWindowPos(game_hwnd,HWND_TOP,r.left,r.top,r.right-r.left,r.bottom-r.top,SWP_FRAMECHANGED|SWP_SHOWWINDOW|SWP_ASYNCWINDOWPOS|SWP_NOOWNERZORDER);
    Sleep(500);save(apply?"applied_borderless_full_monitor":"preview_20_second_automatic_restore",applied);
    if(apply)ExitProcess(applied?0:6);
    for(unsigned i=0;i<80&&IsWindow(game_hwnd);i++)Sleep(250);
    if(IsWindow(game_hwnd)){
        DWORD actual_pid=0;GetWindowThreadProcessId(game_hwnd,&actual_pid);
        if(actual_pid==game_pid){
            SetWindowLongPtrW(game_hwnd,GWL_STYLE,style);SetWindowLongPtrW(game_hwnd,GWL_EXSTYLE,ex);
            SetWindowPlacement(game_hwnd,&before);
            SetWindowPos(game_hwnd,HWND_NOTOPMOST,old_rect.left,old_rect.top,old_rect.right-old_rect.left,old_rect.bottom-old_rect.top,SWP_FRAMECHANGED|SWP_ASYNCWINDOWPOS|SWP_NOOWNERZORDER);
        }
    }
    Sleep(500);save("restored",FALSE);ExitProcess(applied?0:6);
}
