/* 原厂 SDK 的受限双端握手。嵌套 ASync 消息先排队，SDK 方法返回后才派发，禁止递归重入。 */
struct pin_delivery {unsigned node,bytes,source;void *message;};
static struct pin_delivery pin_deliveries[32];
static unsigned pin_head,pin_count;
static unsigned char pin_gate;

static unsigned pin_u32(const unsigned char *p) {unsigned value;memcpy(&value,p,4);return value;}
static int pin_property(const unsigned char *p,unsigned node) {
    return pin_index(p,node)>=0 && pin_u32(p+12)==node;
}
int a7r5_pin_step_valid(const unsigned char *p,unsigned bytes,unsigned source,unsigned node) {
    if(!p || bytes<32 || !dataflow_node(node))return -1024;
    unsigned command=p[26]|(unsigned)p[27]<<8;
    unsigned length=command==1 || command==0x100 || command==0x101?40:command==2?24:48;
    if((command!=1 && command!=2 && command!=0x100 && command!=0x8100 && command!=0x101 && command!=0x8101) ||
       bytes!=length+24 || pin_u32(p+8)!=(1U|bytes<<16) || pin_u32(p+12)!=24 || pin_u32(p+16)!=bytes ||
       p[21] || p[22] || p[23] || (p[20]!=0 && p[20]!=0x7f) ||
       p[24]!=0 || p[25]!=0x10 || p[28]!=length || p[29] ||
       p[30]!=(command==1 || command==2?2:1) || p[31])return -1024;
    if(command==1) {
        if((source>>16)!=0x81cf || pin_u32(p)!=source || !pin_property(p+32,node) || !pin_property(p+48,pin_u32(p+60)))return -1024;
    } else if(command==2) {
        if((source>>16)!=0x81cf || pin_u32(p)!=source || !pin_property(p+32,node))return -1024;
    } else {
        unsigned completed=command==0x8100 || command==0x8101;
        if(!dataflow_node(source) || pin_u32(p) || !pin_property(p+32,completed?node:source) ||
           !pin_property(p+48,completed?source:node))return -1024;
    }
    return 0;
}
static int pin_process(struct pin_delivery item) {
    unsigned char *p=item.message;unsigned command=p[26]|(unsigned)p[27]<<8;
    if(!command)return pin_query(item.message,item.bytes,item.source,item.node);
    unsigned own_offset=command==0x100 || command==0x101?48:32;
    int index=pin_index(p+own_offset,item.node);
    if(index<0)return -1024;
    struct virtual_pin *object=pin_object(index);int result;
    if(command==1 || command==2) {
        const char *name=command==1?"_ZN16DataflowInfraPin14RequestConnectEPK24_MSG_PIN_REQUEST_CONNECTj":
            "_ZN16DataflowInfraPin17RequestDisconnectEPK27_MSG_PIN_REQUEST_DISCONNECTj";
        int (*call)(void *,const void *,unsigned)=next(name);
        result=call(object->pin,p+24,item.source);
    } else {
        const char *name=command==0x100?"_ZN16DataflowInfraPin7ConnectEPK16_MSG_PIN_CONNECT":
            command==0x8100?"_ZN16DataflowInfraPin11ConnectCompEPK21_MSG_PIN_CONNECT_COMP":
            command==0x101?"_ZN16DataflowInfraPin10DisconnectEPK19_MSG_PIN_DISCONNECT":
            "_ZN16DataflowInfraPin14DisconnectCompEPK24_MSG_PIN_DISCONNECT_COMP";
        int (*call)(void *,const void *)=next(name);result=call(object->pin,p+24);
    }
    unsigned state=0,peer[4]={0};
    void (*get_state)(void *,void *)=next("_ZN16DataflowInfraPin11GetPinStateEPN19DefDataflowInfraPin8PinStateE");
    int (*get_peer)(void *,void *)=next("_ZN16DataflowInfraPin12GetTargetPinEPN19DefDataflowInfraPin12PIN_PROPERTYE");
    get_state(object->pin,&state);get_peer(object->pin,peer);
    if(command==0x8100 && !result && !state)__atomic_fetch_add(&pin_connections,1,__ATOMIC_RELEASE);
    printf("MEDIA_DATAFLOW_PIN_STEP node=%#x command=%#x state=%u peer=%#x,%#x,%u,%#x result=%d original_sdk=1 virtual_input=1\n",
           item.node,command,state,peer[0],peer[1],peer[2],peer[3],result);fflush(0);
    if(!result) {int (*release)(unsigned,void *)=next("osal_free_msg");release(item.node,item.message);}
    return result;
}
static int dataflow_dispatch(unsigned node,void *message,unsigned bytes,unsigned source) {
    unsigned char *p=message;unsigned command=p[26]|(unsigned)p[27]<<8;
    int valid=command?a7r5_pin_step_valid(p,bytes,source,node):a7r5_pin_query_valid(p,bytes,source,node);
    if(valid) {if(pin_draining)pin_transport_error=valid;return valid;}
    unsigned outer=!pin_draining;
    if(outer) {
        int (*pause)(unsigned)=next("usleep");
        for(unsigned attempt=0;__atomic_test_and_set(&pin_gate,__ATOMIC_ACQUIRE);attempt++) {
            if(attempt==1000)return -1021;
            pause(1000);
        }
        pin_draining=1;pin_transport_error=0;
    }
    if(pin_count==32) {
        if(!outer)pin_transport_error=-1021;
        if(outer) {pin_draining=0;__atomic_clear(&pin_gate,__ATOMIC_RELEASE);}
        return -1021;
    }
    pin_deliveries[(pin_head+pin_count)%32]=(struct pin_delivery){node,bytes,source,message};pin_count++;
    if(!outer)return 0;
    int result=0;unsigned dispatched=0;
    while(pin_count) {
        struct pin_delivery item=pin_deliveries[pin_head];pin_head=(pin_head+1)%32;pin_count--;
        result=pin_process(item);
        /* 原厂 RequestConnect 等会忽略内部 Sender 返回码，必须独立拦住失败状态。 */
        if(pin_transport_error) {
            printf("MEDIA_DATAFLOW_FATAL transport=%d command_node=%#x pending=%u\n",pin_transport_error,item.node,pin_count);
            fflush(0);_exit(125);
        }
        if(result) {
            /* 初始请求失败仍归调用者；内部请求失败必须停止，不能让已接收的状态继续运行。 */
            if(dispatched || pin_count) {printf("MEDIA_DATAFLOW_FATAL result=%d pending=%u\n",result,pin_count);fflush(0);_exit(125);}
            break;
        }
        if(++dispatched==64 && pin_count) {printf("MEDIA_DATAFLOW_FATAL dispatch_limit\n");fflush(0);_exit(125);}
    }
    pin_draining=0;__atomic_clear(&pin_gate,__ATOMIC_RELEASE);return result;
}
