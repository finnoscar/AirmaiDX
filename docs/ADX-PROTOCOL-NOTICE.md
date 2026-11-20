# ADX protocol references

AirmaiDX implements its USB HID and serial input paths in Swift, Python, and C#. Device identity and input fields were checked against `AdxHidInput`, `NproDevice`, and `MaimollerDeviceNative` in [AquaMai](https://github.com/MewoLab/AquaMai/tree/c64077a2e2ecaa4f557f09fec84028a058940944). The AquaMai Apache-2.0 license and documentation notice are in `Sources/AirmaiCore/Resources`.

The CDC touch path for USB devices `2E3C:5767` and `2E3C:5768` draws on the public behavior documented by [adx-mai2io-dll](https://github.com/alfredodeux/adx-mai2io-dll), including its `pytests/touchTest.py` reference. AirmaiDX does not bundle that project’s binaries or copy its test implementation.

These integrations cover recognized input layouts. The ADX backend does not write calibration or firmware, change EEPROM settings, or implement the NPro WinUSB game channel. Input and accessory coverage varies by controller and firmware.
