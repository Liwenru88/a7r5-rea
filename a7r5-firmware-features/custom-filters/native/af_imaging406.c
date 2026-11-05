#include "af_imaging406.h"
#include "af_factory406.h"
#include "af_runtime_ap406.h"
#ifdef AF_RECIPE_BRIDGE406
static AfImaging406RecipeSource recipe_source;
static uint32_t recipe_source_state;
int af_imaging406_bind_recipe_source(const AfImaging406RecipeSource *source){
    if(!source||source->version!=AF_IMAGING406_RECIPE_SOURCE_VERSION||source->bytes!=sizeof(*source)||
       !source->context||!source->capture)return AF_INVALID;
    uint32_t expected=0;
    if(!__atomic_compare_exchange_n(&recipe_source_state,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return AF_BUSY;
    recipe_source=*source;__atomic_store_n(&recipe_source_state,2,__ATOMIC_RELEASE);return AF_OK;
}
#else
int af_imaging406_bind_recipe_source(const AfImaging406RecipeSource *source){(void)source;return AF_INVALID;}
#endif
_Static_assert(AF_AP_IMAGING_FACTORY_RESTORE==AF_APPLY_CAP_FACTORY_RESTORE,
               "UI与通信恢复能力必须一致");
_Static_assert(AF_AP_IMAGING_SNAPSHOT_OVERLAY==AF_APPLY_CAP_SNAPSHOT_OVERLAY,
               "UI与通信覆盖能力必须一致");
_Static_assert(AF_AP_IMAGING_FULL_RECIPE==AF_APPLY_CAP_FULL_RECIPE,
               "UI与完整配方通信能力必须一致");
_Static_assert(AF_AP_IMAGING_USER20==AF_APPLY_CAP_USER20,
               "UI与全部用户槽通信能力必须一致");
_Static_assert(AF_AP_IMAGING_SECTOR_MATRIX==AF_APPLY_CAP_SECTOR_MATRIX,
               "UI与16色相区配方通信能力必须一致");
static uint32_t capabilities(void *context){
    uint32_t caps=context?af_ap_runtime_preset_capabilities():0;
#ifdef AF_RECIPE_BRIDGE406
    if(!caps&&context&&af_ap_runtime_native_only_capable())
        return AF_AP_IMAGING_REQUIRED|AF_AP_IMAGING_NATIVE_ONLY;
    if(__atomic_load_n(&recipe_source_state,__ATOMIC_ACQUIRE)!=2)caps&=~(AF_APPLY_CAP_FULL_RECIPE|AF_APPLY_CAP_USER20|AF_APPLY_CAP_SECTOR_MATRIX);
#else
    caps&=~(AF_APPLY_CAP_FULL_RECIPE|AF_APPLY_CAP_USER20|AF_APPLY_CAP_SECTOR_MATRIX);
#endif
    return caps;
}
static int send(void *context,uint32_t slot,const AfPreset *preset){
    if(!context||!preset)return AF_INVALID;
    if(!preset->kind)return af_ap_runtime_send_preset(slot,preset);
#ifdef AF_RECIPE_BRIDGE406
    if(preset->kind==1&&(capabilities(context)&AF_APPLY_CAP_FULL_RECIPE))
        return af_ap_runtime_send_stored_recipe(slot,preset,recipe_source.capture,recipe_source.context,2000);
#endif
    return AF_INVALID;
}
static int factory(void *context,uint32_t selector,AfPreset *out){
    return af_ap_factory406_snapshot((uintptr_t)context,selector,out);
}
static int release(void *context){
    return context?af_ap_runtime_release_preset():AF_INVALID;
}
int af_imaging406_binding(uintptr_t base,AfApImagingBinding *out){
    uintptr_t p=(uintptr_t)out;
    if(!base||(base&4095u)||base>UINTPTR_MAX-AF_AP_IMAGE_SPAN||!out||
       p>UINTPTR_MAX-sizeof(*out)||!(p+sizeof(*out)<=base||base+AF_AP_IMAGE_SPAN<=p))return AF_INVALID;
    if((af_ap_runtime_preset_capabilities()&AF_AP_IMAGING_REQUIRED)!=AF_AP_IMAGING_REQUIRED)return AF_BUSY;
    *out=(AfApImagingBinding){AF_AP_IMAGING_VERSION,sizeof(*out),(void *)base,capabilities,send,factory,release};
    return AF_OK;
}
