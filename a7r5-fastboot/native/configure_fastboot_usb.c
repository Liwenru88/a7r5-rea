#include <stdio.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <CoreFoundation/CoreFoundation.h>
int main(void) {
    io_iterator_t it=0; io_service_t svc;
    kern_return_t kr=IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching(kIOUSBDeviceClassName),&it);
    if(kr!=KERN_SUCCESS) return 1;
    IOUSBDeviceInterface **selected=NULL;
    while((svc=IOIteratorNext(it))) {
        IOCFPlugInInterface **plugin=NULL; IOUSBDeviceInterface **dev=NULL; SInt32 score;
        kr=IOCreatePlugInInterfaceForService(svc,kIOUSBDeviceUserClientTypeID,kIOCFPlugInInterfaceID,&plugin,&score);
        IOObjectRelease(svc);
        if(kr!=KERN_SUCCESS || !plugin) continue;
        HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID),(LPVOID*)&dev);
        (*plugin)->Release(plugin);
        if(hr || !dev) continue;
        UInt16 vid=0,pid=0;(*dev)->GetDeviceVendor(dev,&vid);(*dev)->GetDeviceProduct(dev,&pid);
        if(vid==0x18d1 && pid==0x4ee0) {
            if (selected) {
                (*dev)->Release(dev);
                (*selected)->Release(selected);
                IOObjectRelease(it);
                fprintf(stderr, "Multiple Fastboot USB devices\n");
                return 4;
            }
            selected=dev;
        } else {
            (*dev)->Release(dev);
        }
    }
    IOObjectRelease(it);
    if (!selected) return 2;
    UInt8 current=0;
    (*selected)->GetConfiguration(selected,&current);
    printf("Fastboot USB configuration=%u\n",current);
    kr=(*selected)->USBDeviceOpen(selected);
    printf("USBDeviceOpen=0x%08x\n",kr);
    if(kr==KERN_SUCCESS) {
        kr=(*selected)->SetConfiguration(selected,1);
        printf("SetConfiguration(1)=0x%08x\n",kr);
        (*selected)->USBDeviceClose(selected);
    }
    (*selected)->Release(selected);
    return kr==KERN_SUCCESS?0:3;
}
