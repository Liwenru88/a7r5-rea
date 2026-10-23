/* 只构造RAM账户副本：仅替换唯一root记录的密码哈希和shell。 */
static int password_hash_valid(const char *hash) {
    const char prefix[]="$6$rounds=10000$";
    size_t prefix_n=sizeof(prefix)-1;
    if(strlen(hash)!=prefix_n+16+1+86||memcmp(hash,prefix,prefix_n))return 0;
    for(size_t i=prefix_n;i<prefix_n+16+1+86;i++){
        if(i==prefix_n+16){if(hash[i]!='$')return 0;continue;}
        char c=hash[i];
        if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='.'||c=='/'))return 0;
    }
    return 1;
}
static int private_account(const char *original,int length,const char *hash,char output[8192]) {
    int offset=0,found=0,used=0;
    if(!password_hash_valid(hash)||length<=0||length>=8192||original[length-1]!='\n')return -1;
    for(int i=0;i<length;i++)if(!original[i]||original[i]=='\r')return -1;
    while(offset<length){
        int end=offset;while(end<length&&original[end]!='\n')end++;
        if(end==length)return -1;
        int count=end-offset+1;
        if(count>=5&&!memcmp(original+offset,"root:",5)){
            int positions[6],colons=0;
            for(int i=offset;i<end;i++)if(original[i]==':'){
                if(colons==6)return -1;
                positions[colons++]=i;
            }
            if(++found!=1||colons!=6||positions[2]-positions[1]!=2||original[positions[1]+1]!='0'||
               positions[3]-positions[2]!=2||original[positions[2]+1]!='0'||
               end-positions[5]-1!=10||memcmp(original+positions[5]+1,"/bin/false",10))return -1;
            int middle=positions[5]-positions[1]+1,hash_n=(int)strlen(hash);
            if(used+5+hash_n+middle+8>=8192)return -1;
            memcpy(output+used,"root:",5);used+=5;
            memcpy(output+used,hash,(size_t)hash_n);used+=hash_n;
            memcpy(output+used,original+positions[1],(size_t)middle);used+=middle;
            memcpy(output+used,"/bin/sh\n",8);used+=8;
        }else{
            if(used+count>=8192)return -1;
            memcpy(output+used,original+offset,(size_t)count);used+=count;
        }
        offset=end+1;
    }
    return found==1?used:-1;
}
