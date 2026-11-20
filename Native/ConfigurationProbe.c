#define WIN32_LEAN_AND_MEAN
#include <windows.h>
/* Self-authored read-only Win32 INI check. No game DLL, network or CRT. */
static WCHAR config[32768],value[32768];
static void text(const char *s) {
    DWORD n=0,w;while(s[n])n++;WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),s,n,&w,0);
}
static void number(const char *label,DWORD value) {
    char digits[16];unsigned n=0;
    text(label);text("=");
    do{digits[n++]=(char)('0'+value%10);value/=10;}while(value);
    while(n){char one[2]={digits[--n],0};text(one);}text("\n");
}
static int check(const WCHAR *key,const char *label) {
    SetLastError(0);
    DWORD n=GetPrivateProfileStringW(L"vfs",key,L"",value,32768,config);
    DWORD ini_error=GetLastError();
    text(label);number("_chars",n);
    text(label);number("_ini_error",ini_error);
    SetLastError(0);
    DWORD attributes=n && n<32767?GetFileAttributesW(value):INVALID_FILE_ATTRIBUTES;
    text(label);number("_directory_error",GetLastError());
    int good=attributes!=INVALID_FILE_ATTRIBUTES && (attributes&FILE_ATTRIBUTE_DIRECTORY);
    text(label);text(good?"=1\n":"=0\n");return good;
}
void mainCRTStartup(void) {
    number("config_probe_version",2);
    number("config_codepage",GetACP());
    if(!SetCurrentDirectoryW(L"C:\\AirmaiDX\\Package")){text("config_workdir=0\n");ExitProcess(6);}
    DWORD n=GetEnvironmentVariableW(L"SEGATOOLS_CONFIG_PATH",config,32768);
    DWORD attributes=n && n<32768?GetFileAttributesW(config):INVALID_FILE_ATTRIBUTES;
    if(attributes==INVALID_FILE_ATTRIBUTES || (attributes&FILE_ATTRIBUTE_DIRECTORY)){
        text("config_file=0\n");ExitProcess(6);
    }
    text("config_file=1\n");
    SetLastError(0);
    HANDLE file=CreateFileW(config,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,0,OPEN_EXISTING,0,0);
    number("config_open",file!=INVALID_HANDLE_VALUE);
    number("config_open_error",GetLastError());
    if(file!=INVALID_HANDLE_VALUE){
        unsigned char bytes[3];DWORD read=0,encoding=4;
        if(!ReadFile(file,bytes,3,&read,0))encoding=0;
        else if(read>=2 && bytes[0]==0xff && bytes[1]==0xfe)encoding=1;
        else if(read>=2 && bytes[0]==0xfe && bytes[1]==0xff)encoding=2;
        else if(read>=3 && bytes[0]==0xef && bytes[1]==0xbb && bytes[2]==0xbf)encoding=3;
        number("config_encoding",encoding);CloseHandle(file);
    }
    int good=check(L"amfs","config_amfs");
    good=check(L"appdata","config_appdata") && good;
    good=check(L"option","config_option") && good;
    ExitProcess(good?0:6);
}
