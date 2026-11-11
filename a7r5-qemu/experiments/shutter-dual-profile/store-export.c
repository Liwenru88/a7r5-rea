/* 只读导出固定声音记录和目录声明的包，不修改客体文件。 */
typedef unsigned long size_t;
extern int open(const char *,int,...),close(int);
extern long read(int,void *,size_t),write(int,const void *,size_t);
extern void _exit(int) __attribute__((noreturn));
static unsigned char index_data[17800];
static void text(const char *p){size_t n=0;while(p[n])n++;if(write(1,p,n)!=(long)n)_exit(3);}
static void export_file(const char *name){
 char path[128]="/usr/data/lut/";unsigned k=14;
 /* 固定目录前缀长度为14，文件名由固定值或摘要生成。 */
 for(unsigned i=0;name[i]&&k<127;i++)path[k++]=name[i];path[k]=0;
 int fd=open(path,0);if(fd<0)_exit(4);
 text("\nR5_SOUND_FILE_BEGIN:");text(name);text("\n");
 unsigned char raw[256];char hex[513];static const char digits[]="0123456789abcdef";unsigned total=0;
 for(;;){long n=read(fd,raw,sizeof raw);if(n<0)_exit(5);if(!n)break;if((total+=(unsigned)n)>500000)_exit(6);
  for(unsigned i=0;i<(unsigned)n;i++){hex[i*2]=digits[raw[i]>>4];hex[i*2+1]=digits[raw[i]&15];}
  hex[n*2]='\n';if(write(1,hex,n*2+1)!=n*2+1)_exit(7);
 }
 if(close(fd))_exit(8);text("R5_SOUND_FILE_END\n");
}
static void main_export(void){
 int fd=open("/usr/data/lut/R5SOUND.IDX",0);if(fd<0)_exit(9);long n=read(fd,index_data,sizeof index_data);if(close(fd))_exit(10);
 if(n<32||index_data[12]>60||index_data[13]||index_data[14]||index_data[15]||n!=32+index_data[12]*296)_exit(11);
 export_file("R5SOUND.PRO");export_file("R5SOUND.IDX");
 static const char digits[]="0123456789abcdef";
 for(unsigned i=0;i<index_data[12];i++){
  char name[74]="R5SN_";unsigned char *sha=index_data+32+i*296+256;
  for(unsigned j=0;j<32;j++){name[5+j*2]=digits[sha[j]>>4];name[6+j*2]=digits[sha[j]&15];}
  name[69]='.';name[70]='R';name[71]='5';name[72]='S';name[73]=0;export_file(name);
 }
 _exit(0);
}
void _start(void){main_export();}
