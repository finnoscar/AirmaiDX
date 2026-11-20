#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>

/* Original AimeIO 1.0 provider. Only presents explicitly received real card
   access codes. No generated IDs, keyboard hooks, account or network patches. */
#pragma pack(push,1)
typedef struct { char magic[4]; uint16_t version,kind; uint64_t sequence,expires; unsigned char data[16],token[32]; } Event;
typedef struct { char magic[4]; uint64_t sequence,when; unsigned char token[32]; } Ack;
#pragma pack(pop)
static SRWLOCK gate=SRWLOCK_INIT;
static unsigned char token[32],card[10];
static uint64_t previous,until,health_until,acknowledged;
static BOOL initialized,present;
static const WCHAR *config=L"C:\\AirmaiPhoneReader.cfg",*event=L"C:\\AirmaiPhoneCard.dat",
    *ready=L"C:\\AirmaiPhoneReady.dat",*ack=L"C:\\AirmaiPhoneAck.dat";
static void copy(void *dst,const void *src,unsigned n) { volatile unsigned char *a=dst;const unsigned char *b=src;while(n--)*a++=*b++; }
static uint64_t utc(void) { FILETIME f;GetSystemTimeAsFileTime(&f);return ((uint64_t)f.dwHighDateTime<<32)|f.dwLowDateTime; }
static BOOL read_file(const WCHAR *path,void *out,DWORD size) {
    HANDLE h=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,0,OPEN_EXISTING,0,0);
    if(h==INVALID_HANDLE_VALUE)return FALSE;
    LARGE_INTEGER length;DWORD n=0;BOOL ok=GetFileSizeEx(h,&length)&&length.QuadPart==size&&ReadFile(h,out,size,&n,0)&&n==size;
    CloseHandle(h);return ok;
}
static void write_file(const WCHAR *path,const void *data,DWORD size) {
    HANDLE h=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,0,CREATE_ALWAYS,FILE_ATTRIBUTE_HIDDEN,0);
    if(h!=INVALID_HANDLE_VALUE){DWORD n;WriteFile(h,data,size,&n,0);CloseHandle(h);}
}
__declspec(dllexport) uint16_t __stdcall aime_io_get_api_version(void){return 0x0100;}
__declspec(dllexport) HRESULT __stdcall aime_io_init(void){
    unsigned char cfg[40];AcquireSRWLockExclusive(&gate);
    initialized=read_file(config,cfg,40)&&cfg[0]=='A'&&cfg[1]=='M'&&cfg[2]=='C'&&cfg[3]=='P'&&cfg[4]==1&&cfg[5]==0&&cfg[6]==0&&cfg[7]==0;
    if(initialized)copy(token,cfg+8,32);previous=until=health_until=acknowledged=0;present=FALSE;
    ReleaseSRWLockExclusive(&gate);return initialized?S_OK:E_FAIL;
}
__declspec(dllexport) HRESULT __stdcall aime_io_nfc_poll(uint8_t unit){
    if(unit)return E_INVALIDARG;
    AcquireSRWLockExclusive(&gate);
    if(initialized){
        uint64_t now=utc();Ack health={{'A','M','C','R'},0,now,{0}};copy(health.token,token,32);
        if(GetTickCount64()>=health_until){write_file(ready,&health,sizeof(health));health_until=GetTickCount64()+400;}
        Event e;
        if(read_file(event,&e,sizeof(e))){
            unsigned difference=0;for(unsigned i=0;i<32;i++)difference|=e.token[i]^token[i];
            BOOL valid=!difference&&e.magic[0]=='A'&&e.magic[1]=='M'&&e.magic[2]=='C'&&e.magic[3]=='E'&&e.version==1&&e.kind==1&&e.sequence>previous&&e.expires>now&&e.expires-now<=50000000;
            for(unsigned i=0;i<10;i++)if((e.data[i]&15)>9||(e.data[i]>>4)>9)valid=FALSE;
            if(valid){copy(card,e.data,10);previous=e.sequence;until=GetTickCount64()+1200;present=TRUE;DeleteFileW(event);}
        }
        if(GetTickCount64()>until)present=FALSE;
    }
    ReleaseSRWLockExclusive(&gate);return S_OK;
}
__declspec(dllexport) HRESULT __stdcall aime_io_nfc_get_aime_id(uint8_t unit,uint8_t *out,size_t size){
    if(unit||!out||size<10)return E_INVALIDARG;
    AcquireSRWLockExclusive(&gate);
    HRESULT result=S_FALSE;
    if(initialized&&present&&GetTickCount64()<=until){
        copy(out,card,10);Ack receipt={{'A','M','C','A'},previous,utc(),{0}};copy(receipt.token,token,32);
        if(acknowledged!=previous){write_file(ack,&receipt,sizeof(receipt));acknowledged=previous;}result=S_OK;
    }
    ReleaseSRWLockExclusive(&gate);return result;
}
__declspec(dllexport) HRESULT __stdcall aime_io_nfc_get_felica_id(uint8_t unit,uint64_t *out){(void)unit;(void)out;return S_FALSE;}
__declspec(dllexport) void __stdcall aime_io_led_set_color(uint8_t unit,uint8_t r,uint8_t g,uint8_t b){(void)unit;(void)r;(void)g;(void)b;}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved){(void)instance;(void)reason;(void)reserved;return TRUE;}
