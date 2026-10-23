/* 仅供离线 QEMU 测试：串口字节流连接客体回环端口，无主机网络或设备访问。 */
typedef unsigned long size_t;
typedef long ssize_t;
extern int socket(int,int,int),connect(int,const void *,unsigned int),close(int),poll(void *,unsigned long,int);
extern ssize_t read(int,void *,size_t),write(int,const void *,size_t);
struct address { unsigned short family,port; unsigned int ip; unsigned char padding[8]; };
struct pollfd { int fd; short events,revents; };
static int sendall(int fd,const char *data,ssize_t count) {
    while(count>0){ssize_t n=write(fd,data,(size_t)count);if(n<=0)return -1;data+=n;count-=n;} return 0;
}
int main(void) {
    int fd=socket(2,1,0); if(fd<0)return 80;
    struct address addr={2,0xae08,0x0100007f,{0}};
    if(connect(fd,&addr,sizeof(addr))){close(fd);return 81;}
    if(sendall(1,"A7R5_RELAY_READY\n",17)){close(fd);return 82;}
    char buf[4096]; struct pollfd fds[2]={{0,1,0},{fd,1,0}};
    for(;;) {
        if(poll(fds,2,20000)<=0){close(fd);return 83;}
        for(int i=0;i<2;i++) {
            if(fds[i].revents & (1|8|16)) {
                ssize_t n=read(fds[i].fd,buf,sizeof(buf));
                if(n<=0){close(fd);return 0;}
                if(sendall(i?1:fd,buf,n)){close(fd);return 84;}
            }
        }
    }
}
