/* 仅QEMU失败夹具；绝不进入实机材料。 */
#include "../proof.h"
int main(int argc,char **argv){
    if(argc!=2)return 1;struct origin_proof p;
    int fd=open("/tmp_network/" RAM_NAME "/origin.bin",O_RDWR|O_NOFOLLOW);if(fd<0||exact_read(fd,&p,sizeof(p)))return 2;
    switch(argv[1][0]){case 'p':p.pid=2147483647;break;case 's':p.start++;break;case 'n':p.mnt_ino++;break;case 'r':p.root_ino++;break;case 'c':p.caps[2]^=1ULL<<21;break;case 'g':p.groups_count=65;break;case 'm':return fchmod(fd,0600);default:return 3;}
    extern long lseek(int,long,int);if(lseek(fd,0,0))return 4;return write(fd,&p,sizeof(p))==(ssize_t)sizeof(p)?0:5;
}
