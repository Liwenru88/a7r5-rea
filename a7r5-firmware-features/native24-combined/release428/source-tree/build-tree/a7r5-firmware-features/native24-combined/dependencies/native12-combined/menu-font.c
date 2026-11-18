/* 私有菜单的动态 UTF-8 字符串采用原厂简体中文字体，保留当前完整字体属性。 */
typedef unsigned long uintptr_t;
struct image_info { const char *filename;void *base;const char *name;void *address; };
extern void *font_dlsym(void *,const char *);
extern void original_string(void *,const char *);
void native12_menu_font(void *sprite,const char *text) {
    uintptr_t writer[10],created=0;
    void (*ctor)(void *)=font_dlsym(0,"_ZN5alcor19FontAttributeWriterC2Ev");
    void (*fontid)(void *,unsigned)=font_dlsym(0,"_ZN5alcor19FontAttributeWriter9setFontIDEj");
    int (*create)(const void *,void *)=font_dlsym(0,"_ZN2ux6resmgr15ResourceManager10createFontERKN5alcor13FontAttributeERN5libra9RecordPtrE");
    void (*release)(void *)=font_dlsym(0,"_ZN5libra9RecordPtrD1Ev");
    void (*destroy)(void *)=font_dlsym(0,"_ZN5alcor19FontAttributeWriterD2Ev");
    const void *(*getfont)(const void *)=font_dlsym(0,"_ZNK2ux6gfxeng10TextSprite7getFontEv");
    void (*setfont)(void *,const void *)=font_dlsym(0,"_ZN2ux6gfxeng10TextSprite7setFontERKN5libra9RecordPtrE");
    int (*image)(const void *,struct image_info *)=font_dlsym(0,"dladdr");
    struct image_info info;
    if(!ctor||!fontid||!create||!release||!destroy||!getfont||!setfont||!image)goto fallback;
    const void *old=getfont(sprite);
    if(!old||!image((const void *)create,&info)||(uintptr_t)create-(uintptr_t)info.base!=0x170f6cUL)goto fallback;
    uintptr_t base=(uintptr_t)info.base;
    void *manager=*(void **)(base+0x2d2160UL);
    if(!manager)goto fallback;
    ctor(writer);
    /* 固定 libObj 的原生属性合并器，保留字号、颜色、对齐、裁切等全部属性。 */
    if(((int(*)(void *,const void *,void *,unsigned,void *))(base+0x11c1b8UL))(manager,old,writer,0x7ff,0)){
        /* 简称的 ASCII 保留原 Univers 字宽；复用过中文的 sprite 也要恢复字体。 */
        unsigned chinese=0;for(const unsigned char *p=(const unsigned char *)text;*p;p++)if(*p>=128)chinese=1;
        fontid(writer,chinese?0x02066003u:0x02066000u);
        if(create((unsigned char *)writer+12,&created)&&created)setfont(sprite,&created);
    }
    release(&created);destroy(writer);
fallback:
    original_string(sprite,text);
}
