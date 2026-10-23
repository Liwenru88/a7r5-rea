/* 仅QEMU：带长度帧的串口中继，0长度帧传递EOF，不打开主机TCP。 */
typedef unsigned long size_t;
typedef long ssize_t;
extern int socket(int,int,int),connect(int,const void *,unsigned),close(int),poll(void *,unsigned long,int),shutdown(int,int);
extern ssize_t read(int,void *,size_t),write(int,const void *,size_t);
struct address {unsigned short family,port;unsigned ip;unsigned char zero[8];};
struct pollfd {int fd;short events,revents;};
static int all(int fd,const void *raw,unsigned n){const char *p=raw;while(n){ssize_t k=write(fd,p,n);if(k<=0)return -1;p+=k;n-=(unsigned)k;}return 0;}
static int frame(const void *raw,unsigned n){unsigned char h[4]={(unsigned char)n,(unsigned char)(n>>8),(unsigned char)(n>>16),(unsigned char)(n>>24)};return all(1,h,4)||all(1,raw,n);}
int main(void){
    int fd=socket(2,1,0);if(fd<0)return 80;
    struct address a={2,0xae08,0x0100007f,{0}};
    if(connect(fd,&a,sizeof(a))){close(fd);return 81;}
    if(all(1,"A7R5_RELAY_READY\n",17)){close(fd);return 82;}
    struct pollfd p[2]={{0,1,0},{fd,1,0}};unsigned char h[4],data[4096],out[4096];unsigned have=0,size=0,used=0;int reading_header=1;
    for(;;){
        if(poll(p,2,20000)<=0)break;
        if(p[0].fd>=0&&(p[0].revents&(1|8|16))){
            ssize_t n=read(0,reading_header?h+have:data+used,reading_header?4-have:size-used);
            if(n<=0)break;
            if(reading_header){
                have+=(unsigned)n;if(have<4)continue;
                size=(unsigned)h[0]|((unsigned)h[1]<<8)|((unsigned)h[2]<<16)|((unsigned)h[3]<<24);
                if(size>4096)break;
                if(!size){shutdown(fd,1);p[0].fd=-1;continue;}
                used=0;reading_header=0;
            }else{
                used+=(unsigned)n;
                if(used==size){if(all(fd,data,size))break;have=0;reading_header=1;}
            }
        }
        if(p[1].revents&(1|8|16)){
            ssize_t n=read(fd,out,sizeof(out));if(n<=0)break;
            if(frame(out,(unsigned)n)){close(fd);return 84;}
        }
    }
    frame("",0);close(fd);return 0;
}
