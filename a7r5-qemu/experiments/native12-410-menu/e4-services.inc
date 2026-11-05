/* 虚拟触控、输出及成像锁：只接受已观察并由原厂布局核对的请求。 */
static unsigned n12_output_selection,n12_output_configured;
static unsigned n12_output_field9;
static unsigned n12_touch_enabled;
static unsigned n12_imaging_locks;
static unsigned n12_hdmi_definition,n12_hdmi_preset,n12_hdmi_format;
static unsigned n12_aux_configured;
/* 明确的未完成订阅模型：只持有单个请求，不发送完成或状态事件。 */
static void *n12_notify_pending;
static int native12_native_send(unsigned id,void *message,int *handled) {
    *handled=0;
    if(!n12_mailbox||!getenv("A7R5_N12_E4_SERVICES")||!message||!real_msg_size)return 0;
    const unsigned char *p=message;unsigned n=real_msg_size(message);
    if(id==0x90030001&&n>=4){
        if(getenv("A7R5_N12_PENDING_NOTIFY")&&n==12&&p[0]==5&&!p[1]&&p[2]==0x73&&p[3]==0x40&&p[8]==1&&!p[9]&&!p[10]&&!p[11]){
            *handled=1;
            unsigned context=(unsigned)p[4]|(unsigned)p[5]<<8|(unsigned)p[6]<<16|(unsigned)p[7]<<24;
            if(n12_notify_pending||context<0x80000001u||context==0xffffffffu||!real_get_source||real_get_source(message)!=0x80020002)return -1024;
            n12_notify_pending=message;
            record("A7R5_N12_NOTIFY_PENDING ","one subscription queued; no completion or 0x2040 produced; native future remains waiting");
            return 0;
        }
        /* virtual-media-rm.c 已核对的辅助配置；上下文由 +3552cfc 动态分配。 */
        const unsigned char requests[][24]={
            {0,0,0x2c,0x30,3,0,0,0x80},
            {0,0,0x12,0x30,3,0,0,0x80},
            {5,0,0x73,0x40,3,0,0,0x80},
            {5,0,0x2d,0x40,3,0,0,0x80,2,0,1,1,1,1,1,0,1,1,1,1,1},
            {5,0,0x14,0x40,3,0,0,0x80,0,0,1,0,1,0,0,0,1},
            {5,0,0x57,0x40,3,0,0,0x80},
            {5,0,0x9d,0x40,3,0,0,0x80},
            {5,0,0,0x40,3,0,0,0x80,5,0,0,0,0,0,0,0,0,0,1},
            {0,0,3,0x30,3,0,0,0x80}};
        const unsigned lengths[]={24,24,12,24,24,12,12,20,24};
        for(unsigned k=0;k<9;k++)if(p[2]==requests[k][2]&&p[3]==requests[k][3]){
            *handled=1;if(n!=lengths[k]||!real_get_source||!real_allocate_msg||!real_set_source||!real_send_msg||!real_free_msg)return -1024;
            unsigned context=(unsigned)p[4]|(unsigned)p[5]<<8|(unsigned)p[6]<<16|(unsigned)p[7]<<24;
            if(context<0x80000001u||context==0xffffffffu)return -1024;
            for(unsigned i=0;i<n;i++)if((i<4||i>=8)&&p[i]!=requests[k][i])return -1024;
            unsigned queue=real_get_source(message);if(queue!=0x80020002)return -1024;
            unsigned bytes=k==8?16:12,command=(unsigned)p[2]|(unsigned)p[3]<<8;void *reply=0;int rc=real_allocate_msg(queue,&reply,bytes,1);if(rc)return rc;
            unsigned char *r=reply;for(unsigned i=0;i<bytes;i++)r[i]=0;
            r[0]=0x11;r[4]=p[2];r[5]=p[3];r[9]=0xf0;
            real_set_source(reply,id);rc=real_send_msg(queue,reply);if(rc){real_free_msg(queue,reply);return rc;}
            n12_aux_configured|=1u<<k;real_free_msg(id,message);
            char s[120];snprintf(s,sizeof(s),"command=%#x context=%#x configured=%#x virtual_aux=1",command,context,n12_aux_configured);
            record("A7R5_N12_AUX_CONFIG ",s);return 0;
        }
    }
    if(id==0x92840747&&n>=8){
        unsigned command=(unsigned)p[2]|(unsigned)p[3]<<8,recognized=0,valid=0;
        /* 复用现有virtual-media-rm协议证据；这些输出不包含图像生产者。 */
        const unsigned char fixed[][26]={
            {0x0d,0x20,0x21,3,12,0,1,0x80},
            {0x0d,0x20,0x34,3,14,0,1,0x80,0,2},
            {0x0d,0x20,0x2b,3,26,0,1,0x80,0,0,1,0,1,1,1,1},
            {0x0d,0x20,0x38,1,24,0,1,0x80,1,5,5},
            {0x0d,0x20,0x53,1,14,0,1,0x80,3,0,32,75,65},
            {0x0d,0x20,0x52,1,16,0,1,0x80,3,0,1,0,0,0xeb,0x80,0x80},
            {0x0d,0x20,0x62,1,10,0,1,0x80}};
        for(unsigned k=0;k<sizeof(fixed)/sizeof(fixed[0]);k++)if(command==((unsigned)fixed[k][2]|(unsigned)fixed[k][3]<<8)){
            recognized=1;valid=n==fixed[k][4];if(valid)for(unsigned i=0;i<n;i++)if(p[i]!=fixed[k][i])valid=0;
        }
        if(command==0x149||command==0x110){
            recognized=1;valid=n==10&&p[0]==0x0d&&p[1]==0x20&&p[4]==10&&!p[5]&&p[6]==1&&p[7]==0x80&&!p[9]&&
                (p[8]<=1||(command==0x149&&p[8]==15));
        }
        if(recognized){
            *handled=1;
            if(!valid||!real_get_source||!real_allocate_msg||!real_set_source||!real_send_msg||!real_free_msg)return -1024;
            unsigned queue=real_get_source(message);if((queue>>16)!=0x81cf)return -1024;
            void *reply=0;int rc=real_allocate_msg(queue,&reply,12,1);if(rc)return rc;
            for(unsigned i=0;i<12;i++)((unsigned char *)reply)[i]=i<8?p[i]:0;
            ((unsigned char *)reply)[3]|=0x10;((unsigned char *)reply)[4]=12;((unsigned char *)reply)[5]=0;
            real_set_source(reply,id);rc=real_send_msg(queue,reply);if(rc){real_free_msg(queue,reply);return rc;}
            real_free_msg(id,message);char s[100];snprintf(s,sizeof(s),"command=%#x result=0 virtual_output=1",command);
            record("A7R5_N12_OUTPUT_DEPENDENCY ",s);return 0;
        }
    }
    if(id==0x909a015a&&n>=4&&p[0]==0&&p[1]==0x25&&p[3]==1&&(p[2]==0x0a||p[2]==1||p[2]==0x17)){
        *handled=1;unsigned command=p[2];
        if(!real_get_source||!real_allocate_msg||!real_set_source||!real_send_msg||!real_free_msg)return -1024;
        if((n!=12&&n!=16)||p[4]!=n||p[5]||p[6]!=1||p[7])return -1024;
        if(command==0x0a){if(n!=12||p[8]>3||p[9]||p[10]||p[11])return -1024;}
        else if(command==1){if(n!=16||p[8]||p[9]||p[10]||p[11]||p[12]!=6||p[13]||p[14]||p[15])return -1024;}
        else if(n!=12||p[8]>4||(p[9]>6&&p[9]!=0x11)||p[10]!=p[8]||p[11]!=p[9])return -1024;
        unsigned queue=real_get_source(message),value=p[8];if((queue>>16)!=0x81cf)return -1024;
        void *reply=0;int rc=real_allocate_msg(queue,&reply,12,1);if(rc)return rc;
        const unsigned char completion[12]={0,0x25,0,0x81,12,0,1,0};
        for(unsigned i=0;i<12;i++)((unsigned char *)reply)[i]=completion[i];((unsigned char *)reply)[2]=command;
        real_set_source(reply,id);rc=real_send_msg(queue,reply);if(rc){real_free_msg(queue,reply);return rc;}
        if(command==0x0a)n12_hdmi_definition=value;else if(command==1)n12_hdmi_preset=6;else n12_hdmi_format=value;
        real_free_msg(id,message);char s[128];snprintf(s,sizeof(s),"command=%#x definition=%u preset=%u format=%u result=0 virtual_output=1",command,n12_hdmi_definition,n12_hdmi_preset,n12_hdmi_format);
        record("A7R5_N12_HDMI_CONFIG ",s);return 0;
    }
    if(id==0x90040193&&n>=4&&p[2]==0x3d&&p[3]==0x40){
        *handled=1;
        const unsigned char header[4]={5,0,0x3d,0x40};
        if(n!=16||!real_get_source||!real_allocate_msg||!real_set_source||!real_send_msg||!real_free_msg)return -1024;
        for(unsigned i=0;i<4;i++)if(p[i]!=header[i])return -1024;
        /* +3552cfc为原厂分配的动态上下文编号，不能固定成首个样本的2。 */
        unsigned context=(unsigned)p[4]|(unsigned)p[5]<<8|(unsigned)p[6]<<16|(unsigned)p[7]<<24;
        if(!(context&0x80000000u)||context==0x80000000u||context==0xffffffffu)return -1024;
        unsigned mask=(unsigned)p[8]|(unsigned)p[9]<<8|(unsigned)p[10]<<16|(unsigned)p[11]<<24;
        if((mask!=0x8000&&mask!=0x200000)||p[12]>1||p[13]||p[14]||p[15])return -1024;
        unsigned queue=real_get_source(message),enabled=p[12];if(queue!=0x80020002)return -1024;
        void *reply=0;int rc=real_allocate_msg(queue,&reply,12,1);if(rc)return rc;
        /* 原厂legacy future以+4命令号匹配，+8的0xf000表示锁操作完成。 */
        const unsigned char completion[12]={0x11,0,0,0,0x3d,0x40,0,0,0,0xf0,0,0};
        for(unsigned i=0;i<12;i++)((unsigned char *)reply)[i]=completion[i];
        real_set_source(reply,id);rc=real_send_msg(queue,reply);
        if(rc){real_free_msg(queue,reply);return rc;}
        if(enabled)n12_imaging_locks|=mask;else n12_imaging_locks&=~mask;real_free_msg(id,message);
        char s[128];snprintf(s,sizeof(s),"mask=%#x enabled=%u locks=%#x result=0 virtual_imaging=1",mask,enabled,n12_imaging_locks);
        record("A7R5_N12_IMAGING_LOCK ",s);return 0;
    }
    if(id!=0x92840747||n<4||p[3]!=1||(p[2]!=0x18&&p[2]!=0x19&&p[2]!=0x46))return 0;
    *handled=1;
    const unsigned char start[22]={0x0d,0x20,0x18,1,22,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0};
    const unsigned char configure[28]={0x0d,0x20,0x19,1,28,0,1,0x80,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    int valid=n==22;
    /* 原厂 NoWait 初始化另发送 +9=0；仅增加这一份已观察的配置形式。
     * 保存原字段，不将它解释成图像／面板就绪，也不生成图像。 */
    if(valid){for(unsigned i=0;i<20;i++)if(i!=9&&p[i]!=start[i])valid=0;if(p[9]>1||p[20]>2||p[21])valid=0;}
    else if(n==28){valid=1;for(unsigned i=0;i<28;i++)if(p[i]!=configure[i])valid=0;}
    else if(n==10&&p[2]==0x46){
        const unsigned char touch[8]={0x0d,0x20,0x46,1,10,0,1,0x80};valid=1;
        for(unsigned i=0;i<8;i++)if(p[i]!=touch[i])valid=0;if(p[8]>1||p[9])valid=0;
    }
    if(!valid||!real_get_source||!real_allocate_msg||!real_set_source||!real_free_msg||!real_send_msg)return -1024;
    unsigned queue=real_get_source(message),command=p[2],selection=n==22?p[20]:n==10?p[8]:0;
    if((queue>>16)!=0x81cf)return -1024;
    void *reply=0;int rc=real_allocate_msg(queue,&reply,12,1);if(rc)return rc;
    const unsigned char completion[12]={0x0d,0x20,0,0x11,12,0,1,0x80};
    for(unsigned i=0;i<12;i++)((unsigned char *)reply)[i]=completion[i];((unsigned char *)reply)[2]=command;
    real_set_source(reply,id);rc=real_send_msg(queue,reply);
    if(rc){real_free_msg(queue,reply);return rc;}
    if(command==0x46)n12_touch_enabled=selection;
    else {if(command==0x18){n12_output_selection=selection;n12_output_field9=p[9];}n12_output_configured|=command==0x18?1:2;}
    real_free_msg(id,message);
    char s[160];snprintf(s,sizeof(s),"property=%#x selection=%u configured=%u touch=%u result=0 virtual_display=1",command,n12_output_selection,n12_output_configured,n12_touch_enabled);
    record("A7R5_N12_OUTPUT_CONFIG ",s);return 0;
}
