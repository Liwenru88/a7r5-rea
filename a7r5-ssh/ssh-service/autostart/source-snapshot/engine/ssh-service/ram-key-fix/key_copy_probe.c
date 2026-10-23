/* 仅离线QEMU使用：固定合成密钥路径，不包含启动SSH或账户修改接口。 */
#include "../..//src/ns_abi.h"
#include "../private_hostkey.h"
#include "probe_config.h"
int main(int argc,char **argv){(void)argv;if(argc!=1||getuid()||geteuid())return 64;
 int a=open("/simulation/key-copy-source",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
 int b=open("/simulation/key-copy-target",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
 if(a<0||b<0)return 65;struct hostkey_copy result;
 int failed=private_hostkey_copy(a,b,&result);close(a);close(b);
 char row[1024];int n=hostkey_report(row,sizeof(row),PROBE_RUN,&result);
 if(n<=0||(size_t)n>=sizeof(row)||write(1,row,(size_t)n)!=n)return 66;
 return failed?1:0;}
