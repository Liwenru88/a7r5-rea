#include <assert.h>
#include <stdint.h>
#include "r5_shutter.h"

typedef struct {
    int active;
    int allow;
    int install_result;
    int start_result;
    unsigned starts;
    unsigned stops;
    unsigned installs;
    uint32_t generation;
    uint32_t serial;
} FakeAudio;

static int poll_audio(void *context) {
    return ((FakeAudio *)context)->active;
}

static int stop_audio(void *context) {
    ((FakeAudio *)context)->stops++;
    return R5SS_OK;
}

static int authorize_audio(void *context) {
    return ((FakeAudio *)context)->allow;
}

static int install_audio(void *context, uint32_t generation) {
    FakeAudio *audio = context;
    assert(!audio->active);
    if (audio->install_result) return audio->install_result;
    audio->generation = generation;
    audio->installs++;
    return R5SS_OK;
}

static int start_audio(void *context, uint32_t generation, uint32_t serial) {
    FakeAudio *audio = context;
    assert(!audio->active && generation == audio->generation);
    if (audio->start_result) return audio->start_result;
    audio->active = 1;
    audio->serial = serial;
    audio->starts++;
    return R5SS_OK;
}

static void expose(r5ss_scheduler *scheduler, uint32_t seq) {
    assert(r5ss_expose(scheduler, (r5ss_exposure){seq, 0, 0}) == R5SS_OK);
}

int main(void) {
    r5ss_scheduler scheduler;
    FakeAudio audio = {.allow = 1};
    const r5ss_ops operations = {
        &audio, poll_audio, stop_audio, authorize_audio, install_audio, start_audio
    };
    r5ss_init(&scheduler);
    assert(r5ss_configure(&scheduler, 1, 1) == R5SS_OK);

    expose(&scheduler, 10);
    expose(&scheduler, 10);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
    assert(audio.starts == 1 && audio.serial == 1 && scheduler.duplicates == 1);

    /* 连拍只申请一次停止，等原生完成再播放最后一张。 */
    expose(&scheduler, 11);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_BUSY);
    expose(&scheduler, 12);
    expose(&scheduler, 13);
    for (unsigned attempt = 0; attempt < 100000; attempt++) {
        assert(r5ss_tick(&scheduler, &operations) == R5SS_BUSY);
    }
    assert(audio.starts == 1 && audio.stops == 1 && audio.installs == 1);
    audio.active = 0;
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
    assert(audio.starts == 2 && audio.serial == 4 && scheduler.coalesced == 2);

    /* 改配方取消旧触发，真正退休前不会换银行。 */
    expose(&scheduler, 14);
    assert(r5ss_configure(&scheduler, 2, 1) == R5SS_OK);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_BUSY);
    assert(audio.stops == 2 && audio.installs == 1);
    audio.active = 0;
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
    assert(audio.starts == 2);

    /* 原生拒绝未提交时才重试，新曝光继续替换等待项。 */
    audio.install_result = R5SS_BUSY;
    expose(&scheduler, 15);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_BUSY);
    audio.install_result = R5SS_OK;
    audio.start_result = R5SS_BUSY;
    assert(r5ss_tick(&scheduler, &operations) == R5SS_BUSY);
    expose(&scheduler, 16);
    audio.start_result = R5SS_OK;
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
    assert(audio.starts == 3 && audio.generation == 2 && audio.serial == 7);

    /* 播放前重新查静音，未知失败后冻结直到外部确认已退休。 */
    audio.active = 0;
    audio.allow = 0;
    expose(&scheduler, 17);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK && audio.starts == 3);
    audio.active = R5SS_NATIVE;
    assert(r5ss_tick(&scheduler, &operations) == R5SS_NATIVE);
    audio.active = 0;
    audio.allow = 1;
    expose(&scheduler, 18);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_NATIVE && audio.starts == 3);
    assert(r5ss_reset_retired(&scheduler) == R5SS_INVALID);
    assert(r5ss_configure(&scheduler, 0, 0) == R5SS_OK);
    assert(r5ss_reset_retired(&scheduler) == R5SS_OK);
    assert(r5ss_configure(&scheduler, 3, 1) == R5SS_OK);
    expose(&scheduler, 18);
    assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
    assert(audio.starts == 4 && audio.generation == 3);
    /* 十万曝光、重复通知与跨32位编号回绕；调度器占用保持固定。 */
    audio.active = 0;
    assert(r5ss_session(&scheduler) == R5SS_OK);
    scheduler.serial = scheduler.consumed = UINT32_MAX - 5;
    for (unsigned i = 0; i < 100000; i++) {
        uint32_t sequence = UINT32_MAX - 50000 + i;
        unsigned starts = audio.starts;
        expose(&scheduler, sequence);
        expose(&scheduler, sequence);
        assert(r5ss_tick(&scheduler, &operations) == R5SS_OK);
        assert(audio.starts == starts + 1);
        assert(scheduler.serial == scheduler.consumed && scheduler.used <= 64);
        audio.active = 0;
    }
    assert(scheduler.duplicates == 100001);
    return 0;
}
