/* 隔离 USB 边界，用真实保持循环验证生命周期，不访问硬件。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <CoreFoundation/CoreFoundation.h>

static int scenario(const char *name) {
    const char *value=getenv("USB_TEST_SCENARIO");
    return value && !strcmp(value,name);
}
static ULONG fake_release(void *self) { (void)self; return 0; }
static IOReturn fake_vendor(void *self, UInt16 *v) { (void)self; *v=0x18d1; return 0; }
static IOReturn fake_product(void *self, UInt16 *v) { (void)self; *v=0x4ee0; return 0; }
static IOReturn fake_class(void *self, UInt8 *v) { (void)self; *v=255; return 0; }
static IOReturn fake_subclass(void *self, UInt8 *v) { (void)self; *v=66; return 0; }
static IOReturn fake_protocol(void *self, UInt8 *v) { (void)self; *v=3; return 0; }
static IOReturn fake_open(void *self) {
    (void)self; puts("FAKE_OPEN");
    return scenario("busy") ? kIOReturnExclusiveAccess : 0;
}
static IOReturn fake_close(void *self) { (void)self; puts("FAKE_CLOSE"); return 0; }
static IOReturn fake_endpoints(void *self, UInt8 *count) { (void)self; *count=2; return 0; }
static IOReturn fake_pipe(void *self, UInt8 pipe, UInt8 *dir, UInt8 *num,
                           UInt8 *type, UInt16 *packet, UInt8 *interval) {
    (void)self; *dir=pipe==1?kUSBOut:kUSBIn; *num=1;
    *type=kUSBBulk; *packet=512; *interval=0; return 0;
}
static IOReturn fake_write(void *self, UInt8 pipe, void *data, UInt32 size,
                            UInt32 no_data, UInt32 completion) {
    (void)self; (void)pipe; (void)no_data; (void)completion;
    printf("FAKE_WRITE %.*s\n",(int)size,(char *)data); return 0;
}
static IOReturn fake_read(void *self, UInt8 pipe, void *data, UInt32 *size,
                           UInt32 no_data, UInt32 completion) {
    (void)self; (void)pipe; (void)no_data; (void)completion;
    static int reads=0; reads++;
    if(scenario("large_upload") || scenario("oversize_upload")){
        if(reads>1)return kIOReturnNotResponding;
        const char *reply=scenario("large_upload")?"DATA2cb00000":"DATA2cb00001";
        memcpy(data,reply,12);*size=12;return 0;
    }
    if (scenario("read_error") && reads==2) return kIOReturnNotResponding;
    const char *reply=scenario("protocol")?"OKAY1.0":"OKAY0.5";
    memcpy(data,reply,7); *size=7; return 0;
}
static IOUSBInterfaceInterface300 interface={
    .Release=fake_release, .GetDeviceVendor=fake_vendor, .GetDeviceProduct=fake_product,
    .GetInterfaceClass=fake_class, .GetInterfaceSubClass=fake_subclass,
    .GetInterfaceProtocol=fake_protocol, .USBInterfaceOpen=fake_open,
    .USBInterfaceClose=fake_close, .GetNumEndpoints=fake_endpoints,
    .GetPipeProperties=fake_pipe, .WritePipeTO=fake_write, .ReadPipeTO=fake_read,
};
static IOUSBInterfaceInterface300 *interface_pointer=&interface;
static HRESULT fake_query(void *self, REFIID iid, LPVOID *value) {
    (void)self; (void)iid; *value=&interface_pointer; return 0;
}
static IOCFPlugInInterface plugin={.QueryInterface=fake_query,.Release=fake_release};
static IOCFPlugInInterface *plugin_pointer=&plugin;
static int iterator_seen;
static kern_return_t fake_matching(mach_port_t port, CFDictionaryRef matching,
                                   io_iterator_t *it) {
    (void)port; CFRelease(matching); *it=1; iterator_seen=0; return 0;
}
static io_object_t fake_next(io_iterator_t it) {
    (void)it; return scenario("absent") || iterator_seen++ ? 0 : 100;
}
static kern_return_t fake_object_release(io_object_t object) { (void)object; return 0; }
static kern_return_t fake_create_plugin(io_service_t service, CFUUIDRef type,
                                        CFUUIDRef iid, IOCFPlugInInterface ***value,
                                        SInt32 *score) {
    (void)service; (void)type; (void)iid; (void)score;
    *value=&plugin_pointer; return 0;
}
unsigned int fake_sleep(unsigned int seconds) {
    (void)seconds; usleep(10000); return 0;
}
#define IOServiceGetMatchingServices fake_matching
#define IOIteratorNext fake_next
#define IOObjectRelease fake_object_release
#define IOCreatePlugInInterfaceForService fake_create_plugin
#define sleep fake_sleep
#include "read_fastboot_usb.c"
