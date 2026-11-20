/* AMDaemon-only transport compatibility. Redirect only the authorized
 * MuNET HTTP destination to the byte-preserving localhost EOF relay.
 * No game auth checks, machine identities, or response bytes are altered. */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include "TransportConfig.h"
static int (WSAAPI *original_connect)(SOCKET,const struct sockaddr *,int);
static HANDLE log_file=INVALID_HANDLE_VALUE;
static void log_text(const char *text){DWORD n=0,w;while(text[n])n++;if(log_file!=INVALID_HANDLE_VALUE)WriteFile(log_file,text,n,&w,0);}
static int equal(const char *a,const char *b){while(*a && *a==*b){a++;b++;}return *a==*b;}
static int WSAAPI relay_connect(SOCKET socket,const struct sockaddr *address,int len){
    struct sockaddr_in mapped;
    BOOL relayed=FALSE;
    if(address && address->sa_family==AF_INET && len>=(int)sizeof(mapped)){
        const struct sockaddr_in *v4=(const struct sockaddr_in *)address;
        if(airmai_authorized_ip(v4->sin_addr.s_addr) && ntohs(v4->sin_port)==80){
            mapped=*v4;mapped.sin_addr.s_addr=htonl(0x7f000001U);mapped.sin_port=htons(AIRMAI_RELAY_PORT);address=(const struct sockaddr *)&mapped;relayed=TRUE;
        }
    }
    int result=original_connect(socket,address,len);DWORD saved=GetLastError();
    if(relayed)log_text("authorized MuNET HTTP connect forwarded to localhost EOF relay; auth payload unchanged\r\n");
    SetLastError(saved);return result;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved){
    (void)instance;(void)reserved;if(reason!=DLL_PROCESS_ATTACH)return TRUE;DWORD saved=GetLastError();airmai_transport_config();
    log_file=CreateFileW(L"C:\\AirmaiMunetRelay.log",FILE_APPEND_DATA,FILE_SHARE_READ|FILE_SHARE_WRITE,0,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    BYTE *base=(BYTE *)GetModuleHandleW(0);IMAGE_DOS_HEADER *dos=(IMAGE_DOS_HEADER *)base;
    if(dos->e_magic!=IMAGE_DOS_SIGNATURE)return FALSE;
    IMAGE_NT_HEADERS64 *nt=(IMAGE_NT_HEADERS64 *)(base+dos->e_lfanew);
    if(nt->Signature!=IMAGE_NT_SIGNATURE)return FALSE;
    IMAGE_IMPORT_DESCRIPTOR *imports=(IMAGE_IMPORT_DESCRIPTOR *)(base+nt->OptionalHeader.DataDirectory[1].VirtualAddress);
    BOOL installed=FALSE;
    for(;imports->Name;imports++){
        const char *dll=(const char *)(base+imports->Name);if(!equal(dll,"WS2_32.dll") && !equal(dll,"WS2_32.DLL") && !equal(dll,"ws2_32.dll"))continue;
        if(!imports->OriginalFirstThunk)continue;
        IMAGE_THUNK_DATA64 *names=(IMAGE_THUNK_DATA64 *)(base+imports->OriginalFirstThunk),*iat=(IMAGE_THUNK_DATA64 *)(base+imports->FirstThunk);
        for(;names->u1.AddressOfData;names++,iat++){
            BOOL selected=IMAGE_SNAP_BY_ORDINAL64(names->u1.Ordinal)?IMAGE_ORDINAL64(names->u1.Ordinal)==4:equal((const char *)((IMAGE_IMPORT_BY_NAME *)(base+names->u1.AddressOfData))->Name,"connect");
            if(!selected)continue;
            DWORD protection;if(!VirtualProtect(&iat->u1.Function,sizeof(iat->u1.Function),PAGE_READWRITE,&protection))return FALSE;
            original_connect=(void *)(ULONG_PTR)iat->u1.Function;InterlockedExchangePointer((void *volatile *)&iat->u1.Function,relay_connect);
            DWORD ignored;VirtualProtect(&iat->u1.Function,sizeof(iat->u1.Function),protection,&ignored);installed=TRUE;
        }
    }
    log_text(installed?"MuNET HTTP relay installed; transport-only\r\n":"No matching connect import; no change\r\n");SetLastError(saved);return installed;
}
