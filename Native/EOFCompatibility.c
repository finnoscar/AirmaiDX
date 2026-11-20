/* Scoped Winsock EOF compatibility for this Wine profile. Only normalize
 * exceptional readiness when the authorized, established HTTP socket has
 * a readable graceful EOF. Never alter response bytes or auth decisions. */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include "TransportConfig.h"
static int (WSAAPI *original_select)(int,fd_set *,fd_set *,fd_set *,const struct timeval *);
static HANDLE log_file=INVALID_HANDLE_VALUE;
static LONG seen;
static int equal(const char *a,const char *b){while(*a && *a==*b){a++;b++;}return *a==*b;}
static void log_text(const char *text){DWORD n=0,w;while(text[n])n++;if(log_file!=INVALID_HANDLE_VALUE)WriteFile(log_file,text,n,&w,0);}
static BOOL contains(fd_set *set,SOCKET socket){if(!set)return FALSE;for(unsigned i=0;i<set->fd_count;i++)if(set->fd_array[i]==socket)return TRUE;return FALSE;}
static BOOL authorized(SOCKET socket){
    struct sockaddr_in peer;int length=sizeof(peer);if(getpeername(socket,(struct sockaddr *)&peer,&length) || peer.sin_family!=AF_INET)return FALSE;
    unsigned ip=ntohl(peer.sin_addr.s_addr),port=ntohs(peer.sin_port);
    return (airmai_authorized_ip(peer.sin_addr.s_addr) && port==80) || (ip==0x7f000001U && port==AIRMAI_RELAY_PORT);
}
static int WSAAPI compatible_select(int n,fd_set *read,fd_set *write,fd_set *except,const struct timeval *timeout){
    if(InterlockedCompareExchange(&seen,1,0)==0)log_text("EOF compatibility select called\r\n");
    int result=original_select(n,read,write,except,timeout);DWORD saved=GetLastError();
    if(result>0 && read && except){
        for(unsigned i=0;i<except->fd_count;){
            SOCKET socket=except->fd_array[i];
            if(contains(read,socket) && authorized(socket)){
                char peek;int count=recv(socket,&peek,1,MSG_PEEK);
                if(count==0){
                    char urgent;int out_of_band=recv(socket,&urgent,1,MSG_PEEK|MSG_OOB);
                    if(out_of_band<=0){
                        for(unsigned j=i+1;j<except->fd_count;j++)except->fd_array[j-1]=except->fd_array[j];
                        except->fd_count--;result--;log_text("graceful EOF readable; removed false HTTP exception, response unchanged\r\n");continue;
                    }
                }
            }
            i++;
        }
    }
    SetLastError(saved);return result;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved){
    (void)instance;(void)reserved;if(reason!=DLL_PROCESS_ATTACH)return TRUE;DWORD saved=GetLastError();airmai_transport_config();
    log_file=CreateFileW(L"C:\\AirmaiMunetFinCompat.log",FILE_APPEND_DATA,FILE_SHARE_READ|FILE_SHARE_WRITE,0,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,0);
    BYTE *base=(BYTE *)GetModuleHandleW(0);IMAGE_DOS_HEADER *dos=(IMAGE_DOS_HEADER *)base;if(dos->e_magic!=IMAGE_DOS_SIGNATURE)return FALSE;
    IMAGE_NT_HEADERS64 *nt=(IMAGE_NT_HEADERS64 *)(base+dos->e_lfanew);if(nt->Signature!=IMAGE_NT_SIGNATURE)return FALSE;
    IMAGE_IMPORT_DESCRIPTOR *imports=(IMAGE_IMPORT_DESCRIPTOR *)(base+nt->OptionalHeader.DataDirectory[1].VirtualAddress);
    for(;imports->Name;imports++){
        const char *dll=(const char *)(base+imports->Name);if(!equal(dll,"WS2_32.dll") && !equal(dll,"WS2_32.DLL") && !equal(dll,"ws2_32.dll"))continue;
        if(!imports->OriginalFirstThunk)continue;
        IMAGE_THUNK_DATA64 *name=(IMAGE_THUNK_DATA64 *)(base+imports->OriginalFirstThunk),*iat=(IMAGE_THUNK_DATA64 *)(base+imports->FirstThunk);
        for(;name->u1.AddressOfData;name++,iat++){
            BOOL selected=IMAGE_SNAP_BY_ORDINAL64(name->u1.Ordinal)?IMAGE_ORDINAL64(name->u1.Ordinal)==18:equal((const char *)((IMAGE_IMPORT_BY_NAME *)(base+name->u1.AddressOfData))->Name,"select");
            if(!selected)continue;
            DWORD protection;if(!VirtualProtect(&iat->u1.Function,sizeof(iat->u1.Function),PAGE_READWRITE,&protection))return FALSE;
            original_select=(void *)(ULONG_PTR)iat->u1.Function;InterlockedExchangePointer((void *volatile *)&iat->u1.Function,compatible_select);
            DWORD ignored;VirtualProtect(&iat->u1.Function,sizeof(iat->u1.Function),protection,&ignored);log_text("MuNET graceful EOF compatibility installed\r\n");SetLastError(saved);return TRUE;
        }
    }
    SetLastError(saved);return FALSE;
}
