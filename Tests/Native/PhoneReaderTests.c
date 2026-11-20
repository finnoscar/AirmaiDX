#include <assert.h>
#include "../../Native/PhoneReader.c"
static void put(const char* p,const void* b,unsigned n){FILE* f=fopen(p,"wb");assert(f);assert(fwrite(b,1,n,f)==n);fclose(f);}
int main(void){
    assert(sizeof(Event)==72&&sizeof(Ack)==52);
    assert(aime_io_init()==E_FAIL);
    unsigned char cfg[40]={'A','M','C','P',1,0,0,0};for(unsigned i=8;i<40;i++)cfg[i]=(unsigned char)i;
    put("AirmaiPhoneReader.cfg",cfg,40);assert(aime_io_init()==S_OK);
    unsigned char output[10];assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    assert(aime_io_nfc_poll(1)==E_INVALIDARG);
    Event e={{'A','M','C','E'},1,1,100,test_utc+30000000,{0},{0}};
    for(unsigned i=0;i<10;i++)e.data[i]=0x12;memcpy(e.token,cfg+8,32);
    e.token[0]^=1;put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    e.token[0]^=1;e.expires=test_utc-1;put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    e.expires=test_utc+30000000;e.data[0]=0xfa;put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    e.data[0]=0x12;put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);
    assert(aime_io_nfc_get_aime_id(0,output,9)==E_INVALIDARG);assert(aime_io_nfc_get_aime_id(0,output,10)==S_OK);
    for(unsigned i=0;i<10;i++)assert(output[i]==0x12);
    Ack receipt;assert(read_file(ack,&receipt,sizeof(receipt)));assert(receipt.sequence==100&&!memcmp(receipt.token,cfg+8,32));
    test_tick+=1201;aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_FALSE);
    e.sequence++;put("AirmaiPhoneCard.dat",&e,sizeof(e));aime_io_nfc_poll(0);assert(aime_io_nfc_get_aime_id(0,output,10)==S_OK);
    unsigned writes=test_writes;for(unsigned i=0;i<1000;i++)aime_io_nfc_poll(0);assert(test_writes==writes);
    assert(aime_io_nfc_get_felica_id(0,NULL)==S_FALSE);
    puts("native reader checks passed");return 0;
}
