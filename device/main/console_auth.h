#ifndef CONSOLE_AUTH_H
#define CONSOLE_AUTH_H

#include "sdkconfig.h"
#include "settings.h"

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

#endif  // CONSOLE_AUTH_H
