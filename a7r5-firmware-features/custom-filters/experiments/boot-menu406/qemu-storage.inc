/* 只编入实验启动库：真实目录提供者承接两个软件SD库，不改变产品Fsys路径。 */
typedef struct {int fd;unsigned slot;} AfQemuSd;
static int native_media_select(void *,uint32_t);
static AfQemuSd qemu_sd[2]={{-1,0},{-1,1}};
static int qemu_scan(void *context,uint64_t generation,AfMediaList *work,AfMediaList *out){
 AfQemuSd *s=context;
 int (*scan)(int,uint64_t,AfMediaList *,AfMediaList *)=dlsym(repository_handle,"af_media_scan");
 return s&&s->fd>=0&&scan?scan(s->fd,generation,work,out):AF_MANAGE_NOT_READY;
}
static int qemu_read(void *context,const AfMediaList *list,uint32_t index,void *out,size_t capacity,
                     AfMediaSource *info,AfGridProgress progress,void *progress_context){
 AfQemuSd *s=context;
 int (*read_source)(int,const AfMediaList *,uint32_t,void *,size_t,AfMediaSource *,AfGridProgress,void *)=
  dlsym(repository_handle,"af_media_read");
 return s&&s->fd>=0&&read_source?read_source(s->fd,list,index,out,capacity,info,progress,progress_context):AF_MANAGE_NOT_READY;
}
static int af_qemu_media_bind(unsigned slot){
 if(!installed||!repository_context)return AF_BUSY;
 if(slot>1)return AF_INVALID;
 if(qemu_sd[slot].fd<0){
  const char *path=slot?"/tmp/af-sd1":"/tmp/af-sd0";
  int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return AF_IO;
  qemu_sd[slot].fd=fd;
 }
 if(!native_media_source){
  void *p=mmap(0,AF_MEDIA_SOURCE_MAX,3,0x22,-1,0);if(p==(void *)-1)return AF_IO;
  native_media_source=p;
 }
 AfApMediaProviderBinding b={AF_AP_MEDIA_VERSION,sizeof(b),
  {AF_MEDIA_PROVIDER_VERSION,sizeof(AfMediaProvider),&qemu_sd[slot],qemu_scan,qemu_read},native_media_source,AF_MEDIA_SOURCE_MAX};
 if(native_media_bound){
  int (*rebind)(const AfApMediaProviderBinding *)=symbol(&ui,"af_ap_media_provider_rebind");
  return rebind?rebind(&b):AF_STALE;
 }
 int (*bind)(const AfApMediaProviderBinding *)=symbol(&ui,"af_ap_media_provider_bind");
 int (*importer)(void *,AfApMediaProviderImporter *)=dlsym(repository_handle,"af_repository_service_media_provider_importer");
 int (*bind_importer)(const AfApMediaProviderImporter *)=symbol(&ui,"af_ap_media_provider_importer_bind");
 int (*bind_cards)(const AfApMediaCardService *)=symbol(&ui,"af_ap_media_card_service_bind");
 if(!bind||!importer||!bind_importer||!bind_cards)return AF_STALE;
 AfApMediaProviderImporter i;int result=importer(repository_context,&i);if(result)return result;
 if((result=bind(&b)))return result;native_media_bound=1;
 if((result=bind_importer(&i)))return result;native_media_importer_bound=1;
 AfApMediaCardService cards={AF_AP_MEDIA_VERSION,sizeof(cards),&ap_base,native_media_select};
 result=bind_cards(&cards);if(!result)native_media_cards_bound=1;
 return result;
}
