/* 将真实 USB 边界替换为内存接口，测试期间不访问设备。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <CoreFoundation/CoreFoundation.h>

static int scenario(const char *name) {
    const char *value = getenv("USB_TEST_SCENARIO");
    return value && !strcmp(value, name);
}

static ULONG fake_release(void *self) { (void)self; return 0; }
static IOReturn fake_vendor(void *self, UInt16 *value) {
    (void)self; *value = 0x18d1; return kIOReturnSuccess;
}
static IOReturn fake_product(void *self, UInt16 *value) {
    (void)self; *value = 0x4ee0; return kIOReturnSuccess;
}
static IOReturn fake_get_configuration(void *self, UInt8 *value) {
    (void)self;
    if (scenario("read_error")) return kIOReturnNotResponding;
    *value = scenario("configured") ? 1 : 0;
    return kIOReturnSuccess;
}
static IOReturn fake_descriptor(void *self, UInt8 index,
                                IOUSBConfigurationDescriptorPtr *value) {
    (void)self; (void)index;
    static IOUSBConfigurationDescriptor descriptor = {
        .bLength = sizeof(IOUSBConfigurationDescriptor),
        .bDescriptorType = kUSBConfDesc,
        .wTotalLength = sizeof(IOUSBConfigurationDescriptor),
        .bConfigurationValue = 1,
    };
    if (scenario("descriptor_error")) return kIOReturnNotResponding;
    *value = &descriptor;
    return kIOReturnSuccess;
}
static IOReturn fake_open(void *self) {
    (void)self; puts("FAKE_OPEN");
    return scenario("open_error") ? kIOReturnNotReady : kIOReturnSuccess;
}
static IOReturn fake_set_configuration(void *self, UInt8 value) {
    (void)self; printf("FAKE_SET_CONFIGURATION %u\n", value);
    return scenario("set_error") ? kIOReturnNotResponding : kIOReturnSuccess;
}
static IOReturn fake_close(void *self) {
    (void)self; puts("FAKE_CLOSE"); return kIOReturnSuccess;
}
static IOUSBDeviceInterface device = {
    .Release = fake_release,
    .GetDeviceVendor = fake_vendor,
    .GetDeviceProduct = fake_product,
    .GetConfiguration = fake_get_configuration,
    .GetConfigurationDescriptorPtr = fake_descriptor,
    .USBDeviceOpen = fake_open,
    .SetConfiguration = fake_set_configuration,
    .USBDeviceClose = fake_close,
};
static IOUSBDeviceInterface *device_pointer = &device;

static HRESULT fake_query(void *self, REFIID iid, LPVOID *value) {
    (void)self; (void)iid; *value = &device_pointer; return 0;
}
static IOCFPlugInInterface plugin = {.QueryInterface = fake_query, .Release = fake_release};
static IOCFPlugInInterface *plugin_pointer = &plugin;
static kern_return_t fake_matching(mach_port_t port, CFDictionaryRef matching,
                                   io_iterator_t *iterator) {
    (void)port; CFRelease(matching); *iterator = 1; return KERN_SUCCESS;
}
static io_object_t fake_next(io_iterator_t iterator) {
    (void)iterator; static int index = 0;
    int count = scenario("absent") ? 0 : (scenario("multiple") ? 2 : 1);
    return index++ < count ? (io_object_t)(100 + index) : 0;
}
static kern_return_t fake_object_release(io_object_t object) {
    (void)object; return KERN_SUCCESS;
}
static kern_return_t fake_create_plugin(io_service_t service, CFUUIDRef type,
                                        CFUUIDRef interface, IOCFPlugInInterface ***value,
                                        SInt32 *score) {
    (void)service; (void)type; (void)interface; (void)score;
    puts("FAKE_PLUGIN"); *value = &plugin_pointer; return KERN_SUCCESS;
}

#define IOServiceGetMatchingServices fake_matching
#define IOIteratorNext fake_next
#define IOObjectRelease fake_object_release
#define IOCreatePlugInInterfaceForService fake_create_plugin
#include "configure_fastboot_usb.c"
