#include <ws2tcpip.h>
static unsigned AIRMAI_RELAY_PORT=59183;
static ULONG airmai_ips[16];
static unsigned airmai_ip_count;
static BOOL airmai_authorized_ip(ULONG ip) {
    for(unsigned i=0;i<airmai_ip_count;i++)if(airmai_ips[i]==ip)return TRUE;
    return FALSE;
}
static void airmai_transport_config(void) {
    char list[512],port[16];
    if(GetEnvironmentVariableA("AIRMAIDX_RELAY_PORT",port,sizeof(port))) {
        unsigned n=0;for(unsigned i=0;port[i]>='0'&&port[i]<='9';i++)n=n*10+port[i]-'0';
        if(n>=1024&&n<=65535)AIRMAI_RELAY_PORT=n;
    }
    if(!GetEnvironmentVariableA("AIRMAIDX_AUTH_IPV4",list,sizeof(list)))return;
    char *start=list;
    for(char *p=list;;p++) {
        if(*p!=','&&*p)continue;
        char end=*p;*p=0;
        struct in_addr ip;
        if(airmai_ip_count<16&&InetPtonA(AF_INET,start,&ip)==1)airmai_ips[airmai_ip_count++]=ip.s_addr;
        if(!end)break;start=p+1;
    }
}
