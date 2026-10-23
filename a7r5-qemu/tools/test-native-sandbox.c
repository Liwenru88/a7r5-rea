/* 使用与 QEMU 相同的沙箱策略验证实际文件及套接字边界。 */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <unistd.h>
int main(int argc,char **argv){
 assert(argc==6);
 int fd=open(argv[1],O_RDONLY);assert(fd>=0);char b;assert(read(fd,&b,1)==1);close(fd);
 errno=0;fd=open(argv[1],O_WRONLY);assert(fd<0 && (errno==EPERM || errno==EACCES));
 errno=0;fd=open(argv[2],O_RDONLY);assert(fd<0 && (errno==EPERM || errno==EACCES));
 errno=0;fd=open(argv[3],O_WRONLY|O_CREAT,0600);assert(fd<0 && (errno==EPERM || errno==EACCES));
 fd=open(argv[4],O_WRONLY|O_CREAT,0600);assert(fd>=0);assert(write(fd,"ok",2)==2);close(fd);
 int sock=socket(AF_INET,SOCK_STREAM,0);
 if(sock>=0){struct sockaddr_in addr={0};addr.sin_len=sizeof(addr);addr.sin_family=AF_INET;addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);errno=0;assert(bind(sock,(void*)&addr,sizeof(addr))<0 && (errno==EPERM || errno==EACCES));close(sock);}
 else assert(errno==EPERM || errno==EACCES);
 sock=socket(AF_UNIX,SOCK_STREAM,0);assert(sock>=0);struct sockaddr_un addr={0};addr.sun_len=sizeof(addr);addr.sun_family=AF_UNIX;strlcpy(addr.sun_path,argv[5],sizeof(addr.sun_path));assert(bind(sock,(void*)&addr,sizeof(addr))==0);assert(listen(sock,1)==0);close(sock);
 puts("NATIVE_SANDBOX_PASS readonly-input/private-read-denied/outside-write-denied/owned-write/tcp-denied/qmp-unix");return 0;
}
