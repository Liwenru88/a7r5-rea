/* 模型的消息所有权和拒绝路径；不能替代原厂集成验收。 */
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#define A7R5_RM_HOST_TEST 1
static unsigned allocations,releases,sends,last_pool;
static int alloc_error,send_error;
static void *buffer(unsigned size) {unsigned *p=calloc(1,size+4);*p=size;return p+1;}
static int alloc(unsigned id,void **out,int size,int count) {assert(count==1);if(alloc_error)return -1021;*out=buffer(size);allocations++;last_pool=id;return 0;}
static unsigned size(void *p) {return ((unsigned *)p)[-1];}
static int release(unsigned id,void *p) {(void)id;free((unsigned *)p-1);releases++;return 0;}
static void source(void *p,unsigned id) {(void)p;assert(id==0x80d9016e || id==0x90040193 || id==0x90030001 || id==0x909a015a || id==0x92840747);}
static unsigned message_source=0x80020002;
static unsigned get_source(void *p) {(void)p;return message_source;}
static int receive(unsigned id,void **message,long timeout) {(void)id;(void)message;(void)timeout;return 17;}
static int original_future_wait(void *self,unsigned *address,unsigned value,unsigned char timed,long seconds,long nanos) {
 assert(self==(void *)0x1234 && address==(unsigned *)0x5678 && value==9 && timed==1 && seconds==123 && nanos==456);return 1;
}
static unsigned sdk_stage,sdk_fail_stage,sdk_source,sdk_query_state=1;
static unsigned sdk_expected_node=0x90050004,sdk_expected_instance=2;
static void sdk_sender_init(void *p) {memset(p,0,8);}
static void sdk_msg_init(void *p) {memset(p,0,0x198);}
static void sdk_destroy(void *p) {(void)p;}
static void sdk_pin_init(void *p,const void *property,void *sender) {
 /* 原厂 Pin.Send 在对象 +0x2c 读取自身 Node；PIN_PROPERTY 的 Node 是第四项。 */
 (void)sender;const unsigned *own=property;assert(own[0]==0 && own[1]==sdk_expected_instance && own[2]==1 && own[3]==sdk_expected_node);
 memset(p,0,64);((unsigned *)p)[4]=((unsigned *)p)[5]=255;((unsigned *)p)[12]=1;
 memcpy((char *)p+32,property,16);
}
static void sdk_pin_state(void *p,void *out) {*(unsigned *)out=((unsigned *)p)[12];}
static int sdk_pin_peer(void *p,void *out) {memcpy(out,(char *)p+16,16);return 0;}
static int sdk_pin_self(void *p,void *out) {memcpy(out,(char *)p+32,16);return 0;}
static int sdk_set_data(void *p,void *data,unsigned short bytes) {
 assert(bytes==32);if(++sdk_stage==sdk_fail_stage)return -1021;memcpy((char *)p+64,data,bytes);return 0;
}
static int sdk_set_source(void *p,unsigned id) {(void)p;if(++sdk_stage==sdk_fail_stage)return -1021;sdk_source=id;return 0;}
static int sdk_set_reply(void *p,unsigned id) {(void)p;assert(!id);return ++sdk_stage==sdk_fail_stage?-1021:0;}
static int sdk_send(void *sender,unsigned id,void *message) {
 (void)sender;assert(id==0x81cf6198 && sdk_source==sdk_expected_node);
 unsigned *payload=(void *)((char *)message+64);
 assert(payload[0]==0x80001000 && payload[1]==0x20020);
 /* 原厂 +3542918..2940 的接收契约：身份为 +24,+8,+12,+16；状态为 +20。 */
 assert(payload[6]==sdk_expected_node && payload[2]==0 && payload[3]==sdk_expected_instance && payload[4]==1);
 assert(payload[5]==sdk_query_state && !payload[7]);
 return ++sdk_stage==sdk_fail_stage?-1021:0;
}
static int send(unsigned id,void *p) {
 if(send_error)return -1021;
 if(id==0x123 || id==0x90050004)return 17;
 if(id==0x81cf6198) {
  const unsigned char *b=p;assert(size(p)==56 && b[26]>=1 && b[26]<=2 && b[27]==0x80);
  assert(!((unsigned *)p)[12]);release(id,p);return 0;
 }
 assert(id==0x80aa0123 || id==0x80bb0124 || id==0x80020002);sends++;
 if(id==0x80020002 && ((unsigned *)p)[1]==0x3003) {
  assert(size(p)==16 && ((unsigned *)p)[0]==0x11 && ((unsigned *)p)[2]==0xf000 && !((unsigned *)p)[3]);release(id,p);return 0;
 }
 if(id==0x80020002) {assert(size(p)==12 && ((unsigned *)p)[0]==0x11 && (((unsigned *)p)[1]==0x403d || ((unsigned *)p)[1]==0x302c || ((unsigned *)p)[1]==0x4073 || ((unsigned *)p)[1]==0x402d || ((unsigned *)p)[1]==0x4014 || ((unsigned *)p)[1]==0x4057 || ((unsigned *)p)[1]==0x409d || ((unsigned *)p)[1]==0x4000 || ((unsigned *)p)[1]==0x3012) && ((unsigned *)p)[2]==0xf000);release(id,p);return 0;}
 if(size(p)==12) {unsigned short *h=p;assert((h[0]==0x2500 && (h[1]==0x8101 || h[1]==0x810a || h[1]==0x8117)) || (h[0]==0x200d && (h[1]==0x1110 || h[1]==0x1118 || h[1]==0x1119 || h[1]==0x1149 || h[1]==0x1321 || h[1]==0x1334 || h[1]==0x132b || h[1]==0x1138 || h[1]==0x113d || h[1]==0x111a || h[1]==0x1153 || h[1]==0x1152 || h[1]==0x1162)));assert(!((unsigned *)p)[2]);release(id,p);return 0;}
 if(size(p)==7)assert(!memcmp(p,"\2\0\0\6\0\2\0",7));
 else assert(((unsigned *)p)[3]==0);
 release(id,p);return 0;
}
static int sdk_active,sdk_steps,sdk_ignore_send_error;
static int osal_snd_msg(unsigned,void *);
static void sdk_emit(unsigned node,unsigned origin,unsigned command,unsigned bytes,const void *own,const void *peer) {
 unsigned char *p=buffer(bytes+24);unsigned *w=(void *)p;
 w[2]=1|((bytes+24)<<16);w[3]=24;w[4]=bytes+24;
 p[25]=0x10;p[26]=command;p[27]=command>>8;p[28]=bytes;p[30]=command>=0x100 && command<0x8000?1:command>=0x8100?1:2;
 memcpy(p+32,own,16);if(bytes>=40)memcpy(p+48,peer,16);
 unsigned saved=message_source;message_source=origin;
 int rc=osal_snd_msg(node,p);if(!sdk_ignore_send_error)assert(!rc);else if(rc)release(node,p);
 message_source=saved;
}
static int sdk_request_connect(void *pin,const void *payload,unsigned queue) {
 assert(!sdk_active);sdk_active=1;unsigned *p=pin;const unsigned char *b=payload;
 assert(p[12]==1 && queue==0x81cf6198);p[12]=2;p[13]=queue;memcpy(p+4,b+24,16);
 sdk_emit(((const unsigned *)b)[9],p[11],0x100,40,p+8,p+4);
 assert(sdk_steps==0);sdk_steps++;sdk_active=0;return 0;
}
static int sdk_connect(void *pin,const void *payload) {
 assert(!sdk_active);sdk_active=1;unsigned *p=pin;const unsigned char *b=payload;
 assert(p[12]==1 && sdk_steps==1);p[12]=0;memcpy(p+4,b+8,16);
 sdk_emit(((const unsigned *)b)[5],p[11],0x8100,48,p+4,p+8);
 assert(sdk_steps==1);sdk_steps++;sdk_active=0;return 0;
}
static int sdk_connect_comp(void *pin,const void *payload) {
 assert(!sdk_active);sdk_active=1;unsigned *p=pin;(void)payload;
 assert(p[12]==2 && sdk_steps==2);p[12]=0;
 sdk_emit(p[13],p[11],0x8001,32,p+8,0);p[13]=0;sdk_steps++;sdk_active=0;return 0;
}
static int sdk_request_disconnect(void *pin,const void *payload,unsigned queue) {
 (void)payload;assert(!sdk_active);sdk_active=1;unsigned *p=pin;
 assert(p[12]==0 && queue==0x81cf6198);p[12]=2;p[14]=queue;
 sdk_emit(p[7],p[11],0x101,40,p+8,p+4);sdk_active=0;return 0;
}
static int sdk_disconnect(void *pin,const void *payload) {
 assert(!sdk_active);sdk_active=1;unsigned *p=pin;(void)payload;
 assert(p[12]==0);sdk_emit(p[7],p[11],0x8101,48,p+4,p+8);
 p[12]=1;p[4]=p[5]=255;p[6]=p[7]=0;sdk_active=0;return 0;
}
static int sdk_disconnect_comp(void *pin,const void *payload) {
 assert(!sdk_active);sdk_active=1;unsigned *p=pin;(void)payload;
 assert(p[12]==2);p[12]=1;p[4]=p[5]=255;p[6]=p[7]=0;
 sdk_emit(p[14],p[11],0x8002,32,p+8,0);p[14]=0;sdk_active=0;return 0;
}
static void *lookup(void *handle,const char *name) {
 (void)handle;
 if(!strcmp(name,"osal_valloc_msg_wait"))return alloc;
 if(!strcmp(name,"osal_free_msg"))return release;
 if(!strcmp(name,"osal_msg_size"))return size;
 if(!strcmp(name,"osal_set_msg_src"))return source;
 if(!strcmp(name,"osal_get_msg_src"))return get_source;
 if(!strcmp(name,"osal_rcv_msg_tmo"))return receive;
 if(!strcmp(name,"osal_snd_msg"))return send;
 if(!strcmp(name,"usleep"))return usleep;
 if(!strcmp(name,"_ZNSt28__atomic_futex_unsigned_base19_M_futex_wait_untilEPjjbNSt6chrono8durationIlSt5ratioILl1ELl1EEEENS2_IlS3_ILl1ELl1000000000EEEE"))return original_future_wait;
 if(!strcmp(name,"_ZN16DataflowInfraPin14RequestConnectEPK24_MSG_PIN_REQUEST_CONNECTj"))return sdk_request_connect;
 if(!strcmp(name,"_ZN16DataflowInfraPin7ConnectEPK16_MSG_PIN_CONNECT"))return sdk_connect;
 if(!strcmp(name,"_ZN16DataflowInfraPin11ConnectCompEPK21_MSG_PIN_CONNECT_COMP"))return sdk_connect_comp;
 if(!strcmp(name,"_ZN16DataflowInfraPin17RequestDisconnectEPK27_MSG_PIN_REQUEST_DISCONNECTj"))return sdk_request_disconnect;
 if(!strcmp(name,"_ZN16DataflowInfraPin10DisconnectEPK19_MSG_PIN_DISCONNECT"))return sdk_disconnect;
 if(!strcmp(name,"_ZN16DataflowInfraPin14DisconnectCompEPK24_MSG_PIN_DISCONNECT_COMP"))return sdk_disconnect_comp;
 if(!strcmp(name,"_ZN16DataflowInfraPinC1EPN19DefDataflowInfraPin12PIN_PROPERTYEP19DataflowInfraSender"))return sdk_pin_init;
 if(!strcmp(name,"_ZN16DataflowInfraPin11GetPinStateEPN19DefDataflowInfraPin8PinStateE"))return sdk_pin_state;
 if(!strcmp(name,"_ZN16DataflowInfraPin12GetTargetPinEPN19DefDataflowInfraPin12PIN_PROPERTYE"))return sdk_pin_peer;
 if(!strcmp(name,"_ZN16DataflowInfraPin10GetSelfPinEPN19DefDataflowInfraPin12PIN_PROPERTYE"))return sdk_pin_self;
 if(!strcmp(name,"_ZN16DataflowInfraMsgC1Ev"))return sdk_msg_init;
 if(!strcmp(name,"_ZN19DataflowInfraSenderC1Ev"))return sdk_sender_init;
 if(!strcmp(name,"_ZN16DataflowInfraMsgD1Ev") || !strcmp(name,"_ZN19DataflowInfraSenderD1Ev") || !strcmp(name,"_ZN16DataflowInfraPinD1Ev"))return sdk_destroy;
 if(!strcmp(name,"_ZN16DataflowInfraMsg14SetDataflowMsgEPvt"))return sdk_set_data;
 if(!strcmp(name,"_ZN16DataflowInfraMsg8SetSrcIdEj"))return sdk_set_source;
 if(!strcmp(name,"_ZN16DataflowInfraMsg10SetReplyIdEj"))return sdk_set_reply;
 if(!strcmp(name,"_ZN19DataflowInfraSender9SendASyncEjP16DataflowInfraMsg"))return sdk_send;
 abort();
}
void *dlvsym(void *handle,const char *name,const char *version) {(void)handle;assert(!strcmp(name,"dlsym"));assert(!strcmp(version,"GLIBC_2.17"));return lookup;}
#include "../source/guest/virtual-media-rm.c"
static void *request(unsigned op,unsigned bytes) {
 unsigned *p=buffer(bytes);p[0]=op;((unsigned short *)p)[2]=1;((unsigned short *)p)[3]=bytes-24;p[2]=0x80aa0123;p[3]=0xdeadbeef;
 if(op==3)p[6]=0x80bb0124;
 return p;
}
int main(void) {
 const char observation[]="OBS A7R5_MODEL_LOG [set_setting_load]0x0\n";
 assert(a7r5_media_observer_record(observation,sizeof observation-1));
 assert(!a7r5_media_observer_record(observation,sizeof observation-2));
 assert(!a7r5_media_observer_record("Entering exception monitor.\n",28));
 assert(!a7r5_media_observer_record("OBS UNKNOWN fail\n",17));
 assert(a7r5_media_rm_enabled());
 assert(a7r5_future_wait((void *)0x1234,(unsigned *)0x5678,9,1,123,456)==1);
 assert(osal_rcv_msg_tmo(0x80020002,0,-1)==17);
 unsigned char touch[10]={0x0d,0x20,0x46,1,10,0,1,0x80,1,0},reply[16];
 unsigned char event_3003[24]={0,0,3,0x30,3,0,0,0x80};
 assert(!a7r5_aux_event_reply(event_3003,24,reply));
 assert(((unsigned *)reply)[0]==0x11 && ((unsigned *)reply)[1]==0x3003 && ((unsigned *)reply)[2]==0xf000 && !((unsigned *)reply)[3]);
 for(unsigned i=0;i<24;i++) {
  unsigned char bad[24];memcpy(bad,event_3003,24);bad[i]^=0xff;memset(reply,0xcc,16);
  assert(a7r5_aux_event_reply(bad,24,reply)==-1024);for(unsigned j=0;j<16;j++)assert(reply[j]==0xcc);
 }
 assert(!a7r5_touch_reply(touch,10,reply));assert(reply[2]==0x46 && reply[3]==0x11 && !reply[8]);
 for(unsigned i=0;i<10;i++) {
  unsigned char bad[10];memcpy(bad,touch,10);bad[i]=0xff;memset(reply,0xcc,12);
  assert(a7r5_touch_reply(bad,10,reply)==-1024);for(unsigned j=0;j<12;j++)assert(reply[j]==0xcc);
 }
 assert(a7r5_touch_reply(touch,9,reply)==-1024);
 void *p=0;assert(!osal_valloc_msg_wait(0x80d9016e,&p,28,1));assert(last_pool==0x80cf016d);osal_free_msg(0x80d9016e,p);
 for(unsigned i=0;i<4;i++) {
  p=request(3,28);
  if(i==0)((unsigned *)p)[0]=99;
  if(i==1)((unsigned short *)p)[2]=2;
  if(i==2)((unsigned short *)p)[3]=8;
  if(i==3)((unsigned *)p)[2]=0xa5a5a5a5;
  unsigned before=sends;assert(osal_snd_msg(0x80d9016e,p)==-1024);assert(sends==before);release(0,p);
 }
 assert(!osal_snd_msg(0x80d9016e,request(3,28)));assert(sends==2);
 assert(!osal_snd_msg(0x80d9016e,request(9,136)));assert(sends==3);
 assert(allocations==4);assert(releases==10);
 unsigned before=releases;p=request(9,136);alloc_error=1;
 assert(osal_snd_msg(0x80d9016e,p)==-1021);assert(releases==before);alloc_error=0;release(0,p);
 before=releases;p=request(9,136);send_error=1;
 assert(osal_snd_msg(0x80d9016e,p)==-1021);assert(releases==before+1);send_error=0;release(0,p);
 for(unsigned mode=0;mode<4;mode++) {
  void *p=buffer(24);memcpy(p,event_3003,24);unsigned before=releases,old=virtual_aux_event_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && old==virtual_aux_event_configured && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_event_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 message_source=0x80020002;
 unsigned char lock[16]={5,0,0x3d,0x40,2,0,0,0x80,0,0x80,0,0,1,0,0,0};
 unsigned locks=0;assert(!a7r5_release_lock_reply(lock,16,reply,&locks) && locks==0x8000);
 /* 原厂 +355c708..714：+8 不等于 0xf000 时，包装器输出字段为 1。 */
 unsigned ap_status;memcpy(&ap_status,reply+8,4);assert((ap_status!=0xf000)==0);
 lock[12]=0;assert(!a7r5_release_lock_reply(lock,16,reply,&locks) && !locks);lock[12]=1;
 for(unsigned i=0;i<16;i++) {
  unsigned char bad[16];memcpy(bad,lock,16);bad[i]=0xff;memset(reply,0xcc,12);locks=0x200000;
  assert(a7r5_release_lock_reply(bad,16,reply,&locks)==-1024 && locks==0x200000);
  for(unsigned j=0;j<12;j++)assert(reply[j]==0xcc);
 }
 assert(a7r5_release_lock_reply(lock,15,reply,&locks)==-1024);
 unsigned char definition[12]={0,0x25,0x0a,1,12,0,1,0,2,0,0,0};
 assert(!a7r5_hdmi_definition_reply(definition,12,reply) && reply[3]==0x81 && !reply[8]);
 for(unsigned i=0;i<12;i++) {
  unsigned char bad[12];memcpy(bad,definition,12);bad[i]=0xff;memset(reply,0xcc,12);
  assert(a7r5_hdmi_definition_reply(bad,12,reply)==-1024);
  for(unsigned j=0;j<12;j++)assert(reply[j]==0xcc);
 }
 unsigned char preset[16]={0,0x25,1,1,16,0,1,0,0,0,0,0,6,0,0,0};
 assert(!a7r5_hdmi_preset_reply(preset,16,reply) && reply[2]==1 && reply[3]==0x81 && !reply[8]);
 for(unsigned i=0;i<16;i++) {
  unsigned char bad[16];memcpy(bad,preset,16);bad[i]^=0xff;
  assert(a7r5_hdmi_preset_reply(bad,16,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(16);memcpy(p,lock,16);before=releases;unsigned old=virtual_release_locks,old_sends=sends;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90040193,p);
  if(mode<3) {assert(rc<0 && virtual_release_locks==old && sends==old_sends);assert(releases==before+(mode==1));release(0,p);}
  else {assert(!rc && virtual_release_locks==0x8000 && releases==before+2);}
  alloc_error=send_error=0;
 }
 unsigned char auxiliary[24]={0,0,0x2c,0x30,3,0,0,0x80};
 assert(!a7r5_aux_302c_reply(auxiliary,24,reply));memcpy(&ap_status,reply+8,4);assert(ap_status==0xf000);
 for(unsigned i=0;i<24;i++) {
  unsigned char bad[24];memcpy(bad,auxiliary,24);bad[i]^=0xff;memset(reply,0xcc,12);
  assert(a7r5_aux_302c_reply(bad,24,reply)==-1024);for(unsigned j=0;j<12;j++)assert(reply[j]==0xcc);
 }
 assert(a7r5_aux_302c_reply(auxiliary,23,reply)==-1024);
 unsigned char notify_off[12]={5,0,0x73,0x40,3,0,0,0x80};
 unsigned char prepare_3012[24]={0,0,0x12,0x30,3,0,0,0x80};
 assert(!a7r5_aux_302c_reply(prepare_3012,24,reply) && ((unsigned *)reply)[1]==0x3012);
 for(unsigned i=0;i<24;i++) {
  unsigned char bad[24];memcpy(bad,prepare_3012,24);bad[i]^=0xff;
  assert(a7r5_aux_302c_reply(bad,24,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(24);memcpy(p,prepare_3012,24);before=releases;unsigned old=virtual_aux_3012_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && old==virtual_aux_3012_configured && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_3012_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 assert(!a7r5_aux_notify_off_reply(notify_off,12,reply));
 unsigned char still_format[24]={5,0,0x2d,0x40,3,0,0,0x80,2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0};
 assert(!a7r5_aux_still_format_reply(still_format,24,reply));
 unsigned char cap_mode[24]={5,0,0x14,0x40,3,0,0,0x80,0,0,1,0,1,0,0,0,1,0,0,0,0,0,0,0};
 assert(!a7r5_aux_cap_mode_reply(cap_mode,24,reply));
 unsigned char setting_load[12]={5,0,0x57,0x40,3,0,0,0x80};
 unsigned char auxiliary_mode[12]={5,0,0x9d,0x40,3,0,0,0x80};
 unsigned char auxiliary_detail[20]={5,0,0,0x40,3,0,0,0x80,5,0,0,0,0,0,0,0,0,0,1,0};
 assert(!a7r5_aux_detail_reply(auxiliary_detail,20,reply));
 for(unsigned i=0;i<20;i++) {
  unsigned char bad[20];memcpy(bad,auxiliary_detail,20);bad[i]^=0xff;
  assert(a7r5_aux_detail_reply(bad,20,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(20);memcpy(p,auxiliary_detail,20);before=releases;unsigned old=virtual_aux_detail_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && old==virtual_aux_detail_configured && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_detail_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 assert(!a7r5_aux_mode_reply(auxiliary_mode,12,reply));
 for(unsigned i=0;i<12;i++) {
  unsigned char bad[12];memcpy(bad,auxiliary_mode,12);bad[i]^=0xff;
  assert(a7r5_aux_mode_reply(bad,12,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(12);memcpy(p,auxiliary_mode,12);before=releases;unsigned old=virtual_aux_mode_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && old==virtual_aux_mode_configured && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_mode_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 assert(!a7r5_aux_setting_load_reply(setting_load,12,reply));
 for(unsigned i=0;i<12;i++) {
  unsigned char bad[12];memcpy(bad,setting_load,12);bad[i]^=0xff;
  assert(a7r5_aux_setting_load_reply(bad,12,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(12);memcpy(p,setting_load,12);before=releases;unsigned old=virtual_aux_setting_load_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && old==virtual_aux_setting_load_configured && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_setting_load_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 for(unsigned i=0;i<24;i++) {
  unsigned char bad[24];memcpy(bad,cap_mode,24);bad[i]^=0xff;
  assert(a7r5_aux_cap_mode_reply(bad,24,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(24);memcpy(p,cap_mode,24);before=releases;unsigned char old[16];memcpy(old,virtual_aux_cap_mode,16);
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && !memcmp(old,virtual_aux_cap_mode,16) && releases==before+(mode==1));release(0,p);}
  else assert(!rc && !memcmp(virtual_aux_cap_mode,cap_mode+8,16) && releases==before+2);
  alloc_error=send_error=0;
 }
 for(unsigned i=0;i<24;i++) {
  unsigned char bad[24];memcpy(bad,still_format,24);bad[i]^=0xff;
  assert(a7r5_aux_still_format_reply(bad,24,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(24);memcpy(p,still_format,24);before=releases;unsigned char old[16];memcpy(old,virtual_aux_still_format,16);
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && !memcmp(old,virtual_aux_still_format,16) && releases==before+(mode==1));release(0,p);}
  else assert(!rc && !memcmp(virtual_aux_still_format,still_format+8,16) && releases==before+2);
  alloc_error=send_error=0;
 }
 for(unsigned i=0;i<12;i++) {
  unsigned char bad[12];memcpy(bad,notify_off,12);bad[i]^=0xff;
  assert(a7r5_aux_notify_off_reply(bad,12,reply)==-1024);
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(12);memcpy(p,notify_off,12);before=releases;unsigned old=virtual_aux_notify_configured;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && virtual_aux_notify_configured==old && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_notify_configured==1 && releases==before+2);
  alloc_error=send_error=0;
 }
 for(unsigned mode=0;mode<4;mode++) {
  p=buffer(24);memcpy(p,auxiliary,24);before=releases;unsigned old=virtual_aux_302c_value;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80020002;
  int rc=osal_snd_msg(0x90030001,p);
  if(mode<3) {assert(rc<0 && virtual_aux_302c_value==old && releases==before+(mode==1));release(0,p);}
  else assert(!rc && virtual_aux_302c_value==0x80000003 && releases==before+2);
  alloc_error=send_error=0;
 }
 for(unsigned command=0;command<2;command++)for(unsigned mode=0;mode<4;mode++) {
  unsigned length=command?16:12;p=buffer(length);memcpy(p,command?preset:definition,length);
  before=releases;unsigned old_sends=sends,old_definition=virtual_hdmi_definition,old_preset=virtual_hdmi_preset;
  alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80aa0123;
  int rc=osal_snd_msg(0x909a015a,p);
  if(mode<3) {assert(rc<0 && sends==old_sends && virtual_hdmi_definition==old_definition && virtual_hdmi_preset==old_preset);assert(releases==before+(mode==1));release(0,p);}
  else {assert(!rc && releases==before+2);assert(command?virtual_hdmi_preset==6:virtual_hdmi_definition==2);}
  alloc_error=send_error=0;
 }
 unsigned char output[14][28]={
  {0,0x25,0x17,1,12,0,1,0,0,0,0,0},
  {0x0d,0x20,0x18,1,22,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0},
  {0x0d,0x20,0x19,1,28,0,1,0x80,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0x0d,0x20,0x49,1,10,0,1,0x80,1,0},
  {0x0d,0x20,0x21,3,12,0,1,0x80,0,0,0,0},
  {0x0d,0x20,0x34,3,14,0,1,0x80,0,2,0,0,0,0},
  {0x0d,0x20,0x2b,3,26,0,1,0x80,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0},
  {0x0d,0x20,0x10,1,10,0,1,0x80,0,0},
  {0x0d,0x20,0x38,1,24,0,1,0x80,1,5,5,0,0,0,0,0,0,0,0,0,0,0,0,0},
  {0x0d,0x20,0x3d,1,10,0,1,0x80,0,1},
  {0x0d,0x20,0x1a,1,14,0,1,0x80,1,14,0,14,6,0},
  {0x0d,0x20,0x53,1,14,0,1,0x80,3,0,32,75,65,0},
  {0x0d,0x20,0x52,1,16,0,1,0x80,3,0,1,0,0,0xeb,0x80,0x80},
  {0x0d,0x20,0x62,1,10,0,1,0x80,0,0}};
 for(unsigned k=0;k<14;k++) {
  unsigned length=output[k][4];
  int (*build)(const unsigned char *,unsigned,unsigned char *)=k>=8?a7r5_output_fixed_reply:k==7?a7r5_panel_mode_reply:k>=4?a7r5_adf_path_reply:k==3?a7r5_panel_mode_reply:k?a7r5_output_config_reply:a7r5_hdmi_flags_reply;
  assert(!build(output[k],length,reply));assert(build(output[k],length-1,reply)==-1024);
  /* 独立核对消费者匹配字段，不能仅以“发送成功”替代正确的完成回复。 */
  assert(reply[0]==output[k][0] && reply[1]==output[k][1] && reply[2]==output[k][2]);
  assert(reply[3]==(k?output[k][3]+0x10:0x81) && reply[4]==12 && !reply[5]);
  assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
  for(unsigned i=0;i<length;i++) {
   unsigned char bad[28];memcpy(bad,output[k],length);bad[i]^=0xff;memset(reply,0xcc,12);
   assert(build(bad,length,reply)==-1024);for(unsigned j=0;j<12;j++)assert(reply[j]==0xcc);
  }
  for(unsigned mode=0;mode<4;mode++) {
   p=buffer(length);memcpy(p,output[k],length);before=releases;unsigned old=virtual_output_configured,old_sends=sends;
   alloc_error=mode==0;send_error=mode==1;message_source=mode==2?0xa5a5a5a5:0x80aa0123;
   int rc=osal_snd_msg(k?0x92840747:0x909a015a,p);
   if(mode<3) {assert(rc<0 && sends==old_sends && virtual_output_configured==old && releases==before+(mode==1));release(0,p);}
   else assert(!rc && releases==before+2);
   alloc_error=send_error=0;
  }
 }
 for(unsigned selection=0;selection<4;selection++) {
  unsigned char request[22];memcpy(request,output[1],22);request[20]=selection;
  assert(a7r5_output_config_reply(request,22,reply)==(selection<3?0:-1024));
 }
 const unsigned char flags_2[12]={0,0x25,0x17,1,12,0,1,0,2,0x11,2,0x11};
 p=buffer(12);memcpy(p,flags_2,12);message_source=0x80aa0123;
 assert(!osal_snd_msg(0x909a015a,p) && virtual_hdmi_flags==0x11021102);
 p=buffer(48);memset(p,0xa5,48);before=releases;
 assert(osal_snd_msg(0x90050004,p)==17 && releases==before);
 for(unsigned i=0;i<48;i++)assert(((unsigned char *)p)[i]==0xa5);release(0,p);
 for(unsigned format=0;format<=4;format++)for(unsigned rate=0;rate<=7;rate++) {
  unsigned char flags[12];memcpy(flags,flags_2,12);flags[8]=flags[10]=format;flags[9]=flags[11]=rate==7?0x11:rate;
  assert(!a7r5_hdmi_flags_reply(flags,12,reply));
  flags[10]=5;assert(a7r5_hdmi_flags_reply(flags,12,reply)==-1024);
  flags[10]=format;flags[9]=flags[11]=7;assert(a7r5_hdmi_flags_reply(flags,12,reply)==-1024);
 }
 unsigned char pin_request[48]={0x98,0x61,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,48,0,24,0,0,0,48,0,0,0,0x7f,0,0,0,
  0,0x10,0,0,24,0,2,0,0,0,0,0,2,0,0,0,1,0,0,0,0,0,0,0};
 assert(!a7r5_pin_query_valid(pin_request,48,0x81cf6198,0x90050004));
 assert(a7r5_pin_query_valid(pin_request,47,0x81cf6198,0x90050004)==-1024);
 assert(a7r5_pin_query_valid(pin_request,48,0xa5a5a5a5,0x90050004)==-1024);
 assert(a7r5_pin_query_valid(pin_request,48,0x81cf6198,0x9fffaaaa)==-1024);
 for(unsigned i=0;i<48;i++)if(i<4 || i>=8) {
  unsigned char bad[48];memcpy(bad,pin_request,48);bad[i]^=0xff;
  assert(a7r5_pin_query_valid(bad,48,0x81cf6198,0x90050004)==-1024);
 }
 message_source=0x81cf6198;
 for(unsigned node=0;node<2;node++)for(unsigned fail=0;fail<=4;fail++) {
  sdk_expected_node=node?0x9284074a:0x90050004;sdk_expected_instance=node?1:2;
  pin_request[20]=node?0:0x7f;pin_request[36]=sdk_expected_instance;
  assert(!a7r5_pin_query_valid(pin_request,48,0x81cf6198,sdk_expected_node));
  sdk_stage=0;sdk_fail_stage=fail;p=buffer(48);memcpy(p,pin_request,48);before=releases;
  int rc=osal_snd_msg(sdk_expected_node,p);
  if(fail) {assert(rc==-1021 && releases==before && !memcmp(p,pin_request,48));release(0,p);}
  else assert(!rc && releases==before+1);
 }
 unsigned char connect_request[64]={0};unsigned *cw=(void *)connect_request;
 cw[0]=0x81cf6198;cw[2]=0x00400001;cw[3]=24;cw[4]=64;
 connect_request[25]=0x10;connect_request[26]=1;connect_request[28]=40;connect_request[30]=2;
 unsigned own_pin[4]={0,2,1,0x90050004},target_pin[4]={0,1,1,0x9284074a};
 memcpy(connect_request+32,own_pin,16);memcpy(connect_request+48,target_pin,16);
 for(unsigned i=0;i<64;i++)if(i<4 || i>=8) {
  unsigned char bad[64];memcpy(bad,connect_request,64);bad[i]^=0xff;
  assert(a7r5_pin_step_valid(bad,64,0x81cf6198,0x90050004)==-1024);
 }
 sdk_fail_stage=0;message_source=0x81cf6198;p=buffer(64);memcpy(p,connect_request,64);before=releases;
 assert(!osal_snd_msg(0x90050004,p) && sdk_steps==3 && releases==before+4);
 assert(((unsigned *)dataflow_pins[0].pin)[12]==0 && ((unsigned *)dataflow_pins[1].pin)[12]==0);
 assert(!memcmp((char *)dataflow_pins[0].pin+16,target_pin,16) && !memcmp((char *)dataflow_pins[1].pin+16,own_pin,16));
 assert(!pin_count && !pin_draining && !pin_gate);
 /* 连接后的再次查询必须反映持久状态，不能重新构造为未连接端口。 */
 sdk_query_state=0;sdk_stage=sdk_fail_stage=0;sdk_expected_node=0x90050004;sdk_expected_instance=2;
 pin_request[20]=0;pin_request[36]=2;p=buffer(48);memcpy(p,pin_request,48);
 assert(!osal_snd_msg(0x90050004,p));sdk_query_state=1;
 /* 队列满时不接管调用者的请求，原消息仍完整且可由调用者释放。 */
 p=buffer(64);memcpy(p,connect_request,64);pin_count=32;pin_draining=1;before=releases;
 assert(osal_snd_msg(0x90050004,p)==-1021 && releases==before && !memcmp(p,connect_request,64));
 pin_count=pin_draining=0;pin_transport_error=0;release(0,p);
 unsigned char disconnect_request[48]={0};unsigned *dw=(void *)disconnect_request;
 dw[0]=0x81cf6198;dw[2]=0x00300001;dw[3]=24;dw[4]=48;
 disconnect_request[25]=0x10;disconnect_request[26]=2;disconnect_request[28]=24;disconnect_request[30]=2;
 memcpy(disconnect_request+32,own_pin,16);p=buffer(48);memcpy(p,disconnect_request,48);
 assert(!osal_snd_msg(0x90050004,p));
 assert(((unsigned *)dataflow_pins[0].pin)[12]==1 && ((unsigned *)dataflow_pins[1].pin)[12]==1);
 /* 原厂 SDK 忽略内部发送错误时，服务必须终止而不是继续宣称连接完成。 */
 pid_t child=fork();assert(child>=0);
 if(!child) {
  sdk_steps=0;sdk_ignore_send_error=1;send_error=1;p=buffer(64);memcpy(p,connect_request,64);
  osal_snd_msg(0x90050004,p);_exit(99);
 }
 int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==125);
 setenv("A7R5_VIRTUAL_MEDIA_RM","0",1);assert(!a7r5_media_rm_enabled());
 p=buffer(16);memcpy(p,lock,16);before=releases;
 assert(osal_snd_msg(0x123,p)==17 && releases==before);release(0,p);
 puts("VIRTUAL_MEDIA_RM_OWNERSHIP_PASS");return 0;
}
