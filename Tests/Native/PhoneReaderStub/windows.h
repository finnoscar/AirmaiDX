#ifndef WINDOWS_H
#define WINDOWS_H
#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <wchar.h>
#include <string.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#define __declspec(x)
#define __stdcall
#define WINAPI
#define TRUE 1
#define FALSE 0
#define GENERIC_READ 1
#define GENERIC_WRITE 2
#define FILE_SHARE_READ 1
#define FILE_SHARE_DELETE 2
#define OPEN_EXISTING 1
#define CREATE_ALWAYS 2
#define FILE_ATTRIBUTE_HIDDEN 0
#define S_OK 0
#define S_FALSE 1
#define E_FAIL (-1)
#define E_INVALIDARG (-2)
typedef int BOOL;
typedef long HRESULT;
typedef uint32_t DWORD;
typedef wchar_t WCHAR;
typedef FILE* HANDLE;
typedef void* HINSTANCE;
typedef void* LPVOID;
#define INVALID_HANDLE_VALUE NULL
typedef struct { uint32_t dwLowDateTime,dwHighDateTime; } FILETIME;
typedef struct { long long QuadPart; } LARGE_INTEGER;
typedef pthread_mutex_t SRWLOCK;
#define SRWLOCK_INIT PTHREAD_MUTEX_INITIALIZER
static uint64_t test_utc=116444736000000000ULL+17000000000000000ULL,test_tick=100;
static unsigned test_writes;
static void AcquireSRWLockExclusive(SRWLOCK* p){pthread_mutex_lock(p);}
static void ReleaseSRWLockExclusive(SRWLOCK* p){pthread_mutex_unlock(p);}
static void GetSystemTimeAsFileTime(FILETIME* f){f->dwLowDateTime=(uint32_t)test_utc;f->dwHighDateTime=(uint32_t)(test_utc>>32);}
static uint64_t GetTickCount64(void){return test_tick;}
static const char* mapped(const WCHAR* path){static char name[128];const WCHAR* p=wcsrchr(path,L'\\');if(p)path=p+1;unsigned i=0;while(path[i]&&i<127){name[i]=(char)path[i];i++;}name[i]=0;return name;}
static HANDLE CreateFileW(const WCHAR* p,DWORD access,DWORD sharing,void* security,DWORD creation,DWORD flags,void* templ){(void)sharing;(void)security;(void)flags;(void)templ;if(access==GENERIC_WRITE)test_writes++;return fopen(mapped(p),creation==CREATE_ALWAYS?"wb":"rb");}
static BOOL GetFileSizeEx(HANDLE h,LARGE_INTEGER* n){long p=ftell(h);fseek(h,0,SEEK_END);n->QuadPart=ftell(h);fseek(h,p,SEEK_SET);return TRUE;}
static BOOL ReadFile(HANDLE h,void* b,DWORD size,DWORD* n,void* p){(void)p;*n=(DWORD)fread(b,1,size,h);return !ferror(h);}
static BOOL WriteFile(HANDLE h,const void* b,DWORD size,DWORD* n,void* p){(void)p;*n=(DWORD)fwrite(b,1,size,h);return *n==size;}
static void CloseHandle(HANDLE h){fclose(h);}
static BOOL DeleteFileW(const WCHAR* p){return unlink(mapped(p))==0;}
#endif
