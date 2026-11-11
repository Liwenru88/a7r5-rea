#ifndef R5_ASPECT_AP_STATE_H
#define R5_ASPECT_AP_STATE_H
#include <stdint.h>
#include "geometry.h"

/* 独立于原厂 0..3 属性；由链接脚本安排到本模块 BSS。 */
struct aspect_session_state {
    uint32_t restore_claim, save_claim, saved_choice;
    int32_t persist_status;
    uint32_t save_requested;
    uint32_t save_completed, save_seen, save_attempts, restore_attempts;
    uint32_t worker_claim, worker_attempts;
    int32_t worker_error, restore_error;
    uint32_t feedback;
    uint64_t save_outcome, restore_after, save_after, launch_after;
};
_Static_assert(sizeof(struct aspect_session_state) <= 256, "画幅持久化状态越界");
extern struct aspect_session_state aspect_session;
extern uint32_t aspect_selection;
unsigned r5_aspect_publish(unsigned id);
unsigned r5_aspect_get(void);
void r5_aspect_commit(unsigned row);
void r5_aspect_restore_once(void);
int r5_aspect_save(unsigned id);
int r5_aspect_restore_record(const void *data, unsigned bytes, unsigned expected);
unsigned r5_aspect_project_apply(unsigned row);
int r5_aspect_persist_service(void);
unsigned r5_aspect_feedback(void);
#endif
