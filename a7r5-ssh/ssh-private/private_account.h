/* 仅构造RAM副本；不改变UID/GID、密码字段或其他记录。 */
static int private_account(const char *original,int length,char output[8192]) {
    int offset=0,found=0,used=0;
    if(length<=0||length>=8192||original[length-1]!='\n')return -1;
    while(offset<length){
        int end=offset;while(end<length&&original[end]!='\n')end++;
        if(end==length)return -1;
        int count=end-offset+1;
        if(count>=5&&!memcmp(original+offset,"root:",5)){
            int colons=0,last=-1;
            for(int i=offset;i<end;i++)if(original[i]==':'){colons++;last=i;}
            if(++found!=1||colons!=6||end-last-1!=10||memcmp(original+last+1,"/bin/false",10))return -1;
            int prefix=last-offset+1;
            memcpy(output+used,original+offset,(size_t)prefix);used+=prefix;
            memcpy(output+used,"/bin/sh\n",8);used+=8;
        }else{memcpy(output+used,original+offset,(size_t)count);used+=count;}
        offset=end+1;
    }
    return found==1?used:-1;
}
