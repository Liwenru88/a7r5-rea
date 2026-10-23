/* 只捕获已识别的原厂初始化请求，不回复消息、不改动载荷或所有权。 */
static int a7r5_capture_cp_init(const unsigned char *request,unsigned bytes,
                              unsigned destination,unsigned source,unsigned sequence,
                              unsigned char *storage,unsigned storage_bytes) {
    const unsigned char header[8]={5,0,0x63,0x40,3,0,0,0x80};
    if(!request || !storage || ((unsigned long)storage&7) || storage_bytes!=16384 ||
       bytes!=2400 || destination!=0x90030001 ||
       source!=0x80020002 || sequence>=4 || memcmp(request,header,8))return -1;
    unsigned char *slot=storage+sequence*4096;
    /* 完整复制、摘要和元数据就绪后才提交；主机在 QMP 暂停后导出。 */
    if(*(unsigned *)(slot+28))return -1;
    memset(slot,0,4096);
    unsigned values[6]={1,sequence,destination,source,bytes,0};
    unsigned long long hash=14695981039346656037ULL;
    for(unsigned i=0;i<bytes;i++)hash=(hash^request[i])*1099511628211ULL;
    memcpy(slot,"A7CPINIT",8);memcpy(slot+8,values,sizeof values);
    memcpy(slot+32,&hash,8);memcpy(slot+64,request,bytes);
    __atomic_store_n((unsigned *)(slot+28),1,__ATOMIC_RELEASE);
    return 0;
}
