/* 仅用于隔离QEMU的HELLO软件对端，不实现任何成像消费者或硬件设备。 */
#include "af_handshake.h"
#include "af_recipe_transport.h"
extern void *malloc(unsigned long);
extern void free(void *);
static AfHandshake af_qemu_peer;
static void *af_qemu_peer_message;
static unsigned af_qemu_peer_pending;
static uint64_t af_qemu_peer_version;
static AfRecipeRx af_qemu_recipe;
static AfJointAssetDecodeWork af_qemu_decode;
static int af_qemu_peer_enabled(void){return getenv("A7R5_SOFTWARE_AF_PEER")!=0;}
static int af_qemu_peer_allocate(void **out,unsigned size,unsigned wait){
 if(!out || size!=128 || wait || af_qemu_peer_message)return -1024;
 unsigned char *raw=malloc(144);if(!raw)return -1024;
 for(unsigned i=0;i<144;++i)raw[i]=0;
 /* 与既有纯软件OSAL服务相同：size在-8、source由原osal_set_msg_src填写。 */
 *(unsigned *)(raw+8)=128;af_qemu_peer_message=raw+16;*out=raw+16;
 record("AF_QEMU_PEER_ALLOC ","test-only 128B OSAL envelope; no kernel/CP queue");return 0;
}
static int af_qemu_peer_send(void *message){
 unsigned char reply[128];size_t bytes=0;
 if(message!=af_qemu_peer_message || !real_get_source || !real_set_source || !real_msg_size)return -1024;
 const unsigned char *raw=message;
 if(real_msg_size(message)!=128 || real_get_source(message)!=0x80020002u)return -1024;
 if(af_qemu_peer.state==5 && raw[0]=='A' && raw[1]=='7' && raw[2]=='P' && raw[3]=='1'){
  AfApplyPacket p;
  if(af_apply_packet_decode(message,128,&p)!=AF_OK || p.session!=af_qemu_peer.session ||
     p.required!=AF_APPLY_PROTOCOL_REQUIRED || p.operation==AF_APPLY_HELLO || p.version<=af_qemu_peer_version)return -1024;
  af_qemu_peer_version=p.version;
  af_qemu_peer_message=0;free((unsigned char *)message-16);
  record("AF_QEMU_PEER_PARAMETERS ","validated software parameter/native command; no image consumer or pixels");return 0;
 }
 if(af_qemu_peer.state==5 && raw[0]=='A' && raw[1]=='7' && raw[2]=='R' && raw[3]=='1'){
  if(!af_qemu_recipe.magic && af_recipe_rx_init(&af_qemu_recipe,af_qemu_peer.session,AF_RECIPE_CAP_FULL|AF_RECIPE_CAP_SECTOR)!=AF_OK)return -1024;
  if(af_recipe_rx_frame(&af_qemu_recipe,message,128)!=AF_OK)return -1024;
  if(raw[5]==AF_RECIPE_END){
   AfRecipeLease lease;const AfRecipeOwned *owned=0;
   if(af_recipe_rx_validate(&af_qemu_recipe,&af_qemu_decode)!=AF_OK ||
      af_recipe_rx_take(&af_qemu_recipe,&lease,&owned)!=AF_OK || !owned ||
      lease.version<=af_qemu_peer_version ||
      af_recipe_rx_finish(&af_qemu_recipe,&lease,AF_OK,reply,sizeof(reply))!=AF_OK ||
      af_recipe_rx_release(&af_qemu_recipe,&lease)!=AF_OK)return -1024;
   af_qemu_peer_version=lease.version;bytes=128;
   record("AF_QEMU_PEER_RECIPE ","full recipe CRC/SHA/codec and software commit validated; ACK is not image acceptance");
  }else{
   af_qemu_peer_message=0;free((unsigned char *)message-16);return 0;
  }
 }else{
 if(!af_qemu_peer.state && af_hs_server_init(&af_qemu_peer,AF_APPLY_PROTOCOL_REQUIRED))return -1024;
 int owned=af_hs_server(&af_qemu_peer,message,real_msg_size(message),real_get_source(message),reply,sizeof(reply),&bytes);
 if(owned!=1 || bytes!=128){
  record("AF_QEMU_PEER_REJECT ","unsupported or invalid message; no positive acknowledgment");return -1024;
 }
 record("AF_QEMU_PEER_HELLO ","production decoder/server accepted CRC, build, session and capabilities; software fixture only");
 }
 for(unsigned i=0;i<128;++i)((unsigned char *)message)[i]=reply[i];
 real_set_source(message,0x90030001u);
 __atomic_store_n(&af_qemu_peer_pending,1,__ATOMIC_RELEASE);
 return 0;
}
static int af_qemu_peer_take(unsigned id,void **message){
 if(id!=0x80020002u || !message || !__atomic_exchange_n(&af_qemu_peer_pending,0,__ATOMIC_ACQ_REL))return 0;
 *message=af_qemu_peer_message;
 record("AF_QEMU_PEER_DELIVER ","HELLO through original AP receive/parse gate; not a CP imaging result");return 1;
}
static int af_qemu_peer_free(void *message){
 if(!message || message!=af_qemu_peer_message)return 0;
 af_qemu_peer_message=0;free((unsigned char *)message-16);
 record("AF_QEMU_PEER_FREE ","owned software envelope released");return 1;
}
