#include <stdio.h>
#include <string.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <CoreFoundation/CoreFoundation.h>
int main(int argc, char **argv) {
    setbuf(stdout, NULL);
    int check_only = argc == 2 && !strcmp(argv[1], "--check");
    if (argc == 2 && !strcmp(argv[1], "--help")) {
        puts("Usage: configure_fastboot_usb [--check]\n"
             "--check: inspect registry presence only; do not open or configure USB.");
        return 0;
    }
    if (argc != 1 && !check_only) {
        fprintf(stderr, "Usage: configure_fastboot_usb [--check]\n");
        return 64;
    }
    io_iterator_t it=0; io_service_t svc;
    CFMutableDictionaryRef matching = IOServiceMatching(kIOUSBDeviceClassName);
    if (!matching) return 1;
    SInt32 vendor = 0x18d1, product = 0x4ee0;
    CFNumberRef vid = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &vendor);
    CFNumberRef pid = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &product);
    if (!vid || !pid) {
        if (vid) CFRelease(vid);
        if (pid) CFRelease(pid);
        CFRelease(matching);
        return 1;
    }
    CFDictionarySetValue(matching, CFSTR(kUSBVendorID), vid);
    CFDictionarySetValue(matching, CFSTR(kUSBProductID), pid);
    CFRelease(vid); CFRelease(pid);
    kern_return_t kr=IOServiceGetMatchingServices(kIOMainPortDefault,matching,&it);
    if(kr!=KERN_SUCCESS) return 1;
    io_service_t selected_service=0;
    while((svc=IOIteratorNext(it))) {
        if (selected_service) {
            IOObjectRelease(svc);
            IOObjectRelease(selected_service);
            IOObjectRelease(it);
            fprintf(stderr, "Multiple Fastboot USB devices\n");
            return 4;
        }
        selected_service=svc;
    }
    IOObjectRelease(it);
    if (!selected_service) return 2;
    /* 被动检查只读取注册表，不创建 USB 客户端或发送控制请求。 */
    if (check_only) {
        IOObjectRelease(selected_service);
        puts("Fastboot USB present");
        return 0;
    }
    IOCFPlugInInterface **plugin=NULL; IOUSBDeviceInterface **selected=NULL; SInt32 score;
    kr=IOCreatePlugInInterfaceForService(selected_service,kIOUSBDeviceUserClientTypeID,kIOCFPlugInInterfaceID,&plugin,&score);
    IOObjectRelease(selected_service);
    printf("CreatePlugIn=0x%08x\n",kr);
    if(kr!=KERN_SUCCESS || !plugin) return 3;
    HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID),(LPVOID*)&selected);
    (*plugin)->Release(plugin);
    printf("QueryInterface=0x%08x\n",(unsigned)hr);
    if(hr || !selected) return 3;
    UInt8 current=0;
    kr=(*selected)->GetConfiguration(selected,&current);
    printf("GetConfiguration=0x%08x\n",kr);
    if (kr!=KERN_SUCCESS) {
        puts("Fastboot USB configuration=unknown");
        (*selected)->Release(selected);
        return 3;
    }
    printf("Fastboot USB configuration=%u\n",current);
    IOUSBConfigurationDescriptorPtr descriptor=NULL;
    kr=(*selected)->GetConfigurationDescriptorPtr(selected,0,&descriptor);
    printf("GetConfigurationDescriptorPtr=0x%08x\n",kr);
    if (kr!=KERN_SUCCESS || !descriptor ||
        descriptor->bLength < sizeof(IOUSBConfigurationDescriptor) ||
        descriptor->bDescriptorType != kUSBConfDesc || !descriptor->bConfigurationValue) {
        fprintf(stderr, "Configuration descriptor unavailable or invalid\n");
        (*selected)->Release(selected);
        return 3;
    }
    UInt8 desired=descriptor->bConfigurationValue;
    /* 已处于所需配置时保留接口，避免重复销毁和重建。 */
    if (current==desired) {
        puts("Fastboot USB already configured");
        (*selected)->Release(selected);
        return 0;
    }
    kr=(*selected)->USBDeviceOpen(selected);
    printf("USBDeviceOpen=0x%08x\n",kr);
    if(kr==KERN_SUCCESS) {
        kr=(*selected)->SetConfiguration(selected,desired);
        printf("SetConfiguration(%u)=0x%08x\n",desired,kr);
        (*selected)->USBDeviceClose(selected);
    }
    (*selected)->Release(selected);
    return kr==KERN_SUCCESS?0:3;
}
