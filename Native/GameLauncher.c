#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static WCHAR command[4096];
static void report(const char *value) {
    DWORD n=0,w;while(value[n])n++;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),value,n,&w,0);
}
static void report_code(DWORD code) {
    char digits[16];unsigned n=0;do{digits[n++]=(char)('0'+code%10);code/=10;}while(code);
    while(n){char digit[2]={digits[--n],0};report(digit);}
}
static void failure(const char *step,DWORD code) {
    report("{\"launcher_error\":\"");report(step);report("\",\"win32_error\":");
    report_code(code);report("}\n");
}
void WinMainCRTStartup(void) {
    static WCHAR work[32768],flag[8];
    if(!GetEnvironmentVariableW(L"AIRMAIDX_WORKDIR",work,32768)||!SetCurrentDirectoryW(work)){failure("workdir",GetLastError());ExitProcess(2);}
    const WCHAR *normal=L"inject.exe -d -k mai2hook.dll amdaemon.exe -f -c config_common.json config_server.json config_client.json";
    const WCHAR *compat=L"inject.exe -d -k C:\\AirmaiTransport.dll -k C:\\AirmaiEOF.dll -k mai2hook.dll amdaemon.exe -f -c config_common.json config_server.json config_client.json";
    const WCHAR *source=GetEnvironmentVariableW(L"AIRMAIDX_TRANSPORT_FIX",flag,8)?compat:normal;
    unsigned i=0;do{command[i]=source[i];}while(source[i++]);
    STARTUPINFOW si={0};PROCESS_INFORMATION daemon={0},game={0};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES|STARTF_USESHOWWINDOW;
    si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);si.wShowWindow=SW_HIDE;
    if(!CreateProcessW(L"inject.exe",command,0,0,TRUE,0,0,0,&si,&daemon)){failure("inject",GetLastError());ExitProcess(3);}
    Sleep(2000);
    if(WaitForSingleObject(daemon.hProcess,0)==WAIT_OBJECT_0){
        DWORD code=0;GetExitCodeProcess(daemon.hProcess,&code);
        if(code){failure("inject-exit",code);ExitProcess(3);}
    }
    if(!GetEnvironmentVariableW(L"AIRMAIDX_GAME_COMMAND",command,4096)){failure("game-command",GetLastError());ExitProcess(4);}
    si.wShowWindow=SW_SHOWNORMAL;
    if(!CreateProcessW(L"Sinmai.exe",command,0,0,TRUE,0,0,0,&si,&game)){failure("game",GetLastError());ExitProcess(5);}
    report("{\"game\":\"created\"}\n");
    WaitForSingleObject(game.hProcess,INFINITE);
    DWORD status=0;GetExitCodeProcess(game.hProcess,&status);
    report("{\"game_exit_code\":");report_code(status);report("}\n");
    CloseHandle(game.hThread);CloseHandle(game.hProcess);CloseHandle(daemon.hThread);CloseHandle(daemon.hProcess);
    ExitProcess(status);
}
