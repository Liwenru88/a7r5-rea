#ifndef R5SOUND_PROFILES_H
#define R5SOUND_PROFILES_H
#include "r5sound_catalog.h"
#define R5SOUND_PROFILE_COUNT 2u
#define R5SOUND_PROFILE_BYTES 96u
enum { R5SOUND_MECHANICAL=0, R5SOUND_ELECTRONIC=1, R5SOUND_UNKNOWN=2 };
typedef struct {uint8_t identity[32];uint32_t step,selected;} r5sound_profile;
typedef struct {r5sound_profile group[R5SOUND_PROFILE_COUNT];} r5sound_profiles;
/* 只读原厂快门类型：机械及电子前帘共用0，电子为1；未知值禁止播放。 */
unsigned r5sound_profile_from_native(unsigned);
int r5sound_profiles_load(const r5sound_storage *,const r5sound_catalog *,r5sound_profiles *);
/* 一个原子文件包含两组设置；写入失败时不发布新的内存状态。 */
int r5sound_profiles_save(const r5sound_storage *,const r5sound_catalog *,
                        r5sound_profiles *,unsigned,unsigned,unsigned);
unsigned r5sound_profile_selected(unsigned);
unsigned r5sound_profile_volume(unsigned);
int r5sound_profile_request(unsigned,unsigned);
int r5sound_profile_volume_request(unsigned,unsigned);
int r5sound_profile_blocked(unsigned);
const char *r5sound_profile_status(unsigned);
#endif
