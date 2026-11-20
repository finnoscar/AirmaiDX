#include <sys/socket.h>
#include <netinet/in.h>
#include <net/if.h>
#include <stdlib.h>
#include <stdint.h>
#include <arpa/inet.h>
#include <string.h>
#include <errno.h>
/* Per-session routing of the configured server's proxy fake-IP answers.
 * Ports and application bytes are preserved. No auth results are synthesized. */
static const struct sockaddr *route(int fd,const struct sockaddr *address,struct sockaddr_in *mapped) {
    if(address&&address->sa_family==AF_INET) {
        *mapped=*(const struct sockaddr_in *)address;
        const char *routes=getenv("AIRMAIDX_IP_MAP");
        if(routes) {
            char copy[1024];strlcpy(copy,routes,sizeof(copy));char *cursor=copy,*pair;
            while((pair=strsep(&cursor,","))) {
                char *target=strchr(pair,'=');if(!target)continue;*target++=0;
                struct in_addr before,after;
                if(inet_pton(AF_INET,pair,&before)==1&&inet_pton(AF_INET,target,&after)==1&&before.s_addr==mapped->sin_addr.s_addr) {
                    mapped->sin_addr=after;break;
                }
            }
        }
        address=(const struct sockaddr *)mapped;
    }
    const char *name=getenv("AIRMAIDX_BIND_INTERFACE");
    if(name&&name[0]&&address) {
        unsigned index=if_nametoindex(name);
        if(index&&address->sa_family==AF_INET) {
            const struct sockaddr_in *v4=(const struct sockaddr_in *)address;
            uint32_t ip=ntohl(v4->sin_addr.s_addr);
            /* Unmapped proxy fake IPs are reachable only on the system route.
             * A configured fake IP mapped above to its origin still uses the
             * selected interface; unrelated requests retain their proxy route. */
            const int proxy_fake=(ip & 0xfffe0000u)==0xc6120000u; /* 198.18.0.0/15 */
            if((ip>>24)!=127&&!proxy_fake)setsockopt(fd,IPPROTO_IP,IP_BOUND_IF,&index,sizeof(index));
        }
    }
    return address;
}
static int contains_ip(const char *list,struct in_addr address) {
    if(!list)return 0;
    char copy[1024];strlcpy(copy,list,sizeof(copy));char *cursor=copy,*part;
    while((part=strsep(&cursor,","))) {
        struct in_addr value;
        if(inet_pton(AF_INET,part,&value)==1&&value.s_addr==address.s_addr)return 1;
    }
    return 0;
}
static int allowed(int fd,const struct sockaddr *address) {
    if(!getenv("AIRMAIDX_STARTUP_ONLY")||!address||address->sa_family==AF_UNIX||address->sa_family==AF_UNSPEC)return 1;
    struct in_addr ip;unsigned port;
    if(address->sa_family==AF_INET) {
        const struct sockaddr_in *v4=(const struct sockaddr_in *)address;ip=v4->sin_addr;port=ntohs(v4->sin_port);
    } else if(address->sa_family==AF_INET6) {
        const struct sockaddr_in6 *v6=(const struct sockaddr_in6 *)address;
        if(IN6_IS_ADDR_LOOPBACK(&v6->sin6_addr))return 1;
        if(!IN6_IS_ADDR_V4MAPPED(&v6->sin6_addr))return 0;
        memcpy(&ip,&v6->sin6_addr.s6_addr[12],sizeof(ip));port=ntohs(v6->sin6_port);
    } else return 0;
    if((ntohl(ip.s_addr)>>24)==127)return 1;
    int kind=0;socklen_t size=sizeof(kind);
    if(getsockopt(fd,SOL_SOCKET,SO_TYPE,&kind,&size)!=0)return 0;
    if(kind==SOCK_STREAM&&port==443)return contains_ip(getenv("AIRMAIDX_STARTUP_IPS"),ip);
    if(kind==SOCK_DGRAM&&port==53)return contains_ip(getenv("AIRMAIDX_DNS_IPS"),ip);
    return 0;
}
static int bound_connect(int fd,const struct sockaddr *address,socklen_t length) {
    struct sockaddr_in mapped;address=route(fd,address,&mapped);
    if(!allowed(fd,address)){errno=EACCES;return -1;}
    return connect(fd,address,length);
}
static int bound_connectx(int fd,const sa_endpoints_t *ep,sae_associd_t assoc,unsigned flags,const struct iovec *iov,unsigned count,size_t *written,sae_connid_t *id) {
    sa_endpoints_t copy;struct sockaddr_in mapped;
    if(ep){copy=*ep;copy.sae_dstaddr=route(fd,ep->sae_dstaddr,&mapped);ep=&copy;}
    if(ep&&!allowed(fd,ep->sae_dstaddr)){errno=EACCES;return -1;}
    return connectx(fd,ep,assoc,flags,iov,count,written,id);
}
static ssize_t bound_sendto(int fd,const void *data,size_t count,int flags,const struct sockaddr *address,socklen_t length) {
    struct sockaddr_in mapped;address=route(fd,address,&mapped);
    if(!allowed(fd,address)){errno=EACCES;return -1;}
    return sendto(fd,data,count,flags,address,length);
}
static ssize_t bound_sendmsg(int fd,const struct msghdr *msg,int flags) {
    struct msghdr copy;struct sockaddr_in mapped;
    if(msg){copy=*msg;copy.msg_name=(void *)route(fd,msg->msg_name,&mapped);msg=&copy;}
    if(msg&&!allowed(fd,msg->msg_name)){errno=EACCES;return -1;}
    return sendmsg(fd,msg,flags);
}
#define INTERPOSE(replacement,original) \
__attribute__((used)) static struct { const void *new_fn; const void *old_fn; } \
interpose_##original __attribute__((section("__DATA,__interpose"))) = {(const void *)replacement,(const void *)original};
INTERPOSE(bound_connect,connect)
INTERPOSE(bound_connectx,connectx)
INTERPOSE(bound_sendto,sendto)
INTERPOSE(bound_sendmsg,sendmsg)
