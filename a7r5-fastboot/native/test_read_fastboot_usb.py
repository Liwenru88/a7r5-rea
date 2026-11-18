from pathlib import Path

SOURCE = Path(__file__).with_name('read_fastboot_usb.c').read_text()


def test_reader_opens_fastboot_interface_without_device_configuration():
    assert 'SetConfiguration' not in SOURCE
    assert 'kIOUSBInterfaceUserClientTypeID' in SOURCE
    assert 'USBDeviceOpen' not in SOURCE
    assert 'USBInterfaceOpen' in SOURCE
    assert 'IOUSBFindInterfaceRequest' not in SOURCE
    assert 'CreateInterfaceIterator' not in SOURCE
    assert 'IOUSBInterfaceClassName' in SOURCE


def test_reader_reports_interface_and_bulk_endpoints():
    assert 'GetNumEndpoints' in SOURCE
    assert 'GetPipeProperties' in SOURCE
    assert 'USBInterfaceOpen' in SOURCE
    assert 'PIPE %u dir=%u endpoint=%u type=%u packet=%u' in SOURCE
