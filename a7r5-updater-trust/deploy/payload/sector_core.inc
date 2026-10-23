static int full_hash(int fd,char out[65],int short_read)
{
    struct sha_ctx context;
    unsigned char buffer[65536];
    sha_init(&context);
    for(unsigned long offset=0;offset<PARTITION_BYTES;offset+=sizeof(buffer)){
        size_t size=PARTITION_BYTES-offset;
        if(size>sizeof(buffer))size=sizeof(buffer);
        ssize_t got=pread(fd,buffer,size,(long)offset);
        if(short_read&&offset==0)got--;
        if(got!=(ssize_t)size)return -1;
        sha_add(&context,buffer,size);
    }
    unsigned char extra;
    if(pread(fd,&extra,1,PARTITION_BYTES)!=0)return -1;
    sha_end(&context,out);
    return 0;
}

/* 返回值只描述普通文件演练。真实块设备打开、独占和恢复须有新版本准入。 */
int trust_apply_fd(int target,int journal,int fault)
{
    char digest[65];
    unsigned char sector[512];
    unsigned completed=0;
    if(target<0||journal<0||target==journal)return 10;
#ifndef TRUST_HOST_TEST
    if(fault)return 11;
#endif
    sha_bytes(BEFORE_SECTORS,sizeof(BEFORE_SECTORS),digest);
    if(memcmp(digest,BEFORE_PATCH_SHA,65))return 12;
    sha_bytes(AFTER_SECTORS,sizeof(AFTER_SECTORS),digest);
    if(memcmp(digest,AFTER_PATCH_SHA,65))return 12;
    for(unsigned i=0;i<PATCH_COUNT;i++){
        if(PATCH_OFFSETS[i]%512||PATCH_OFFSETS[i]+512>PARTITION_BYTES)return 13;
        if(i&&PATCH_CHECKSUM[i-1]>PATCH_CHECKSUM[i])return 13;
        for(unsigned j=0;j<i;j++)if(PATCH_OFFSETS[i]==PATCH_OFFSETS[j])return 13;
    }
    if(full_hash(target,digest,fault==1)||memcmp(digest,ORIGINAL_SHA,65))return 14;
    if(note(journal,"PREIMAGE_VERIFIED",0,-1,0))return 15;
    for(unsigned i=0;i<PATCH_COUNT;i++){
        long offset=(long)PATCH_OFFSETS[i];
        if(pread(target,sector,512,offset)!=512||memcmp(sector,BEFORE_SECTORS+i*512,512))return 16;
        if(note(journal,"WRITE_BEGIN",completed,offset,0))return 15;
        ssize_t got;
#ifdef TRUST_HOST_TEST
        if(fault==2&&i==0)got=pwrite(target,AFTER_SECTORS+i*512,511,offset);
        else if(fault==3&&i==0)got=-1;
        else
#endif
        got=pwrite(target,AFTER_SECTORS+i*512,512,offset);
        /* 短写不补写；结果不明确时保留现场，不自动恢复。 */
        if(got!=512){(void)note(journal,"STOP_WRITE_UNCERTAIN",completed,offset,17);return 17;}
        completed++;
#ifdef TRUST_HOST_TEST
        if(fault==6&&i==0)return 18;
#endif
        if(note(journal,"WRITE_RETURNED",completed,offset,0))return 18;
        if(i+1==PATCH_COUNT||PATCH_CHECKSUM[i]!=PATCH_CHECKSUM[i+1]){
            if(fsync(target)||(fault==4)){(void)note(journal,"STOP_SYNC_UNCERTAIN",completed,offset,19);return 19;}
            if(note(journal,"PHASE_SYNC_RETURNED",completed,offset,0))return 18;
        }
    }
    if(full_hash(target,digest,0))return 20;
#ifdef TRUST_HOST_TEST
    if(fault==5)digest[0]=digest[0]=='0'?'1':'0';
#endif
    if(memcmp(digest,CANDIDATE_SHA,65))return 20;
    if(note(journal,"FULL_LOGICAL_READBACK_MATCH",completed,-1,0))return 18;
    return 0;
}

