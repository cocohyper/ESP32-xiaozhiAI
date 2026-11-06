#pragma once

// Browser-based WiFi provisioning over the USB/UART serial port.
//
// The device listens on UART0 at 115200 baud for line based commands:
//   WIFICFG:PING
//   WIFICFG:STATUS
//   WIFICFG:SCAN
//   WIFICFG:SET:{"ssid":"...","password":"..."}
//   WIFICFG:RESET
//
// Responses use the same WIFICFG: prefix. See docs/serial-wifi-provision.md
// and tools/serial-wifi-provision/ for the matching browser tool.
// Enabled by CONFIG_SERIAL_PROVISION_ENABLED (default y).
void SerialProvisionStart();
