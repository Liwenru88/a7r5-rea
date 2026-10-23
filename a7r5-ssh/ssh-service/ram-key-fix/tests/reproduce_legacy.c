/* 精确复现真实0755普通文件触发旧109权限分支。 */
#include <stdio.h>
#include <sys/stat.h>
int main(void){unsigned mode=S_IFREG|0755;int reject=!S_ISREG(mode)||(mode&077);printf("legacy_source_mode=%o code=%d permission_rejection=%d\n",mode,reject?109:0,!!(mode&077));return reject?1:0;}
