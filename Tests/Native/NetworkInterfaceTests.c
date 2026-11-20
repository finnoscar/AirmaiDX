#include "../../Native/NetworkInterface.c"
#include <assert.h>
#include <unistd.h>

static void verify_route(const char *input,const char *expected,unsigned bound_if) {
    int fd=socket(AF_INET,SOCK_STREAM,0);
    assert(fd>=0);
    struct sockaddr_in destination={.sin_len=sizeof(destination),.sin_family=AF_INET,.sin_port=htons(443)},mapped;
    assert(inet_pton(AF_INET,input,&destination.sin_addr)==1);
    route(fd,(const struct sockaddr *)&destination,&mapped);
    struct in_addr expected_ip;
    assert(inet_pton(AF_INET,expected,&expected_ip)==1);
    assert(mapped.sin_addr.s_addr==expected_ip.s_addr && mapped.sin_port==destination.sin_port);
    unsigned index=0;socklen_t length=sizeof(index);
    assert(getsockopt(fd,IPPROTO_IP,IP_BOUND_IF,&index,&length)==0);
    assert(index==bound_if);
    close(fd);
}

int main(void) {
    unsigned index=if_nametoindex("lo0");
    assert(index!=0);
    assert(setenv("AIRMAIDX_BIND_INTERFACE","lo0",1)==0);
    assert(setenv("AIRMAIDX_IP_MAP","198.18.0.1=192.0.2.42",1)==0);
    verify_route("198.18.0.1","192.0.2.42",index);
    verify_route("198.18.0.2","198.18.0.2",0);
    verify_route("198.19.255.254","198.19.255.254",0);
    verify_route("198.20.0.1","198.20.0.1",index);
    verify_route("127.0.0.1","127.0.0.1",0);
    return 0;
}
