#ifndef CONSOLE_AUTH_H
#define CONSOLE_AUTH_H

#include "sdkconfig.h"
#include "settings.h"
#include "system_info.h"

#include <string>

// A per-device management credential, never a model provider API key.
// Provision NVS wifi/console_token to override the optional build default.
inline std::string GetConsoleDeviceToken() {
    Settings settings("wifi", false);
    auto token = settings.GetString("console_token");
#ifdef CONFIG_CONSOLE_DEVICE_TOKEN
    if (token.empty()) {
        token = CONFIG_CONSOLE_DEVICE_TOKEN;
    }
#endif
    return token;
}

// Fixed device identity: NVS wifi/device_id > build CONFIG_DEVICE_ID_OVERRIDE > WiFi MAC.
inline std::string GetConsoleDeviceId() {
    Settings settings("wifi", false);
    auto pinned = settings.GetString("device_id");
#ifdef CONFIG_DEVICE_ID_OVERRIDE
    if (pinned.empty()) {
        pinned = CONFIG_DEVICE_ID_OVERRIDE;
    }
#endif
    if (pinned.empty()) {
        return SystemInfo::GetMacAddress();
    }
    return pinned;
}

#endif  // CONSOLE_AUTH_H
