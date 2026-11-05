#ifndef R5_STABLE_IO425_H
#define R5_STABLE_IO425_H
#include "r5_lut_directory.h"
#include "r5_native24_contract.h"
_Static_assert(R5_LOOK_SLOTS==R5_N24_SLOTS,"slot contract");
_Static_assert(R5_LOOK_MAX==R5_N24_FILE_MAX_BYTES,"file contract");
#define R5_STABLE_SCRATCH_BYTES 65537u
/* 同一文件工作线程串行使用，事件和收包回调不得访问。 */
extern uint8_t r5_stable_scratch425[R5_STABLE_SCRATCH_BYTES];
enum r5_stable_file {R5_STABLE_LIBRARY, R5_STABLE_PREVIOUS, R5_STABLE_SELECTION, R5_STABLE_RECOVERY,
 R5_STABLE_TUNE,R5_STABLE_TUNE_RECOVERY};
/* read: 0完整、1缺失、2读写错误、3超长；capacity含一个额外探测字节。 */
int r5_stable_read425(struct r5_lut_directory *,unsigned,uint8_t *,size_t,size_t *);
/* publish: 0同步成功、2发布前失败、3发布不确定。 */
int r5_stable_publish425(struct r5_lut_directory *,unsigned,const uint8_t *,size_t);
int r5_stable_remove425(struct r5_lut_directory *,unsigned);
int r5_grid420_health(void);
#endif
