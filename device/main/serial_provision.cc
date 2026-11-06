#include "serial_provision.h"

#ifdef CONFIG_SERIAL_PROVISION_ENABLED

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include <driver/uart.h>
#include <esp_err.h>
#include <esp_log.h>
#include <esp_system.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <cJSON.h>

#include <ssid_manager.h>
#include <wifi_manager.h>

namespace {

constexpr const char* TAG = "SerialProvision";
constexpr uart_port_t kPort = UART_NUM_0;
constexpr int kRxBufferSize = 4096;
constexpr int kMaxLineSize = 512;

void SendLine(const std::string& line) {
    std::printf("%s\n", line.c_str());
    std::fflush(stdout);
}

std::string JsonToString(cJSON* item) {
    char* encoded = cJSON_PrintUnformatted(item);
    std::string out = encoded ? encoded : "";
    cJSON_free(encoded);
    return out;
}

std::string ToJsonString(const std::string& value) {
    cJSON* item = cJSON_CreateString(value.c_str());
    if (item == nullptr) {
        return "\"\"";
    }
    std::string out = JsonToString(item);
    cJSON_Delete(item);
    return out;
}

void HandleStatus() {
    auto& wifi = WifiManager::GetInstance();
    cJSON* root = cJSON_CreateObject();
    cJSON_AddBoolToObject(root, "initialized", wifi.IsInitialized());
    cJSON_AddBoolToObject(root, "connected", wifi.IsConnected());
    cJSON_AddBoolToObject(root, "config_mode", wifi.IsConfigMode());
    cJSON_AddStringToObject(root, "ssid", wifi.GetSsid().c_str());
    cJSON_AddStringToObject(root, "ip", wifi.GetIpAddress().c_str());
    cJSON_AddNumberToObject(root, "rssi", wifi.GetRssi());
    cJSON_AddStringToObject(root, "ap_ssid", wifi.GetApSsid().c_str());

    cJSON* saved = cJSON_CreateArray();
    for (const auto& item : SsidManager::GetInstance().GetSsidList()) {
        cJSON_AddItemToArray(saved, cJSON_CreateString(item.ssid.c_str()));
    }
    cJSON_AddItemToObject(root, "saved_ssids", saved);

    std::string payload = JsonToString(root);
    cJSON_Delete(root);
    SendLine("WIFICFG:STATUS:" + payload);
}

void HandleScan() {
    if (!WifiManager::GetInstance().IsInitialized()) {
        SendLine("WIFICFG:ERR:not_initialized");
        return;
    }

    wifi_scan_config_t scan_config = {};
    scan_config.show_hidden = false;
    scan_config.scan_type = WIFI_SCAN_TYPE_ACTIVE;
    scan_config.scan_time.active.min = 100;
    scan_config.scan_time.active.max = 300;

    esp_err_t err = esp_wifi_scan_start(&scan_config, true);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "WiFi scan failed: %s", esp_err_to_name(err));
        SendLine(std::string("WIFICFG:ERR:scan_failed:") + esp_err_to_name(err));
        return;
    }

    uint16_t ap_num = 0;
    if (esp_wifi_scan_get_ap_num(&ap_num) != ESP_OK) {
        ap_num = 0;
    }
    if (ap_num > 30) {
        ap_num = 30;
    }

    std::vector<wifi_ap_record_t> records(ap_num > 0 ? ap_num : 1);
    uint16_t got = ap_num;
    if (got > 0 && esp_wifi_scan_get_ap_records(&got, records.data()) != ESP_OK) {
        got = 0;
    }

    std::vector<std::pair<int, std::string>> found;
    for (uint16_t i = 0; i < got; ++i) {
        std::string ssid(reinterpret_cast<const char*>(records[i].ssid));
        if (ssid.empty()) {
            continue;
        }
        found.emplace_back(static_cast<int>(records[i].rssi), ssid);
    }
    std::sort(found.begin(), found.end(),
              [](const auto& a, const auto& b) { return a.first > b.first; });

    cJSON* array = cJSON_CreateArray();
    std::vector<std::string> seen;
    int limit = 0;
    for (const auto& item : found) {
        if (std::find(seen.begin(), seen.end(), item.second) != seen.end()) {
            continue;
        }
        if (++limit > 20) {
            break;
        }
        seen.push_back(item.second);
        cJSON* o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "ssid", item.second.c_str());
        cJSON_AddNumberToObject(o, "rssi", item.first);
        cJSON_AddItemToArray(array, o);
    }

    std::string payload = JsonToString(array);
    cJSON_Delete(array);
    SendLine("WIFICFG:SCAN:" + payload);
}

void HandleSet(const std::string& payload) {
    cJSON* root = cJSON_Parse(payload.c_str());
    if (root == nullptr) {
        SendLine("WIFICFG:ERR:bad_json");
        return;
    }

    cJSON* ssid_item = cJSON_GetObjectItem(root, "ssid");
    cJSON* password_item = cJSON_GetObjectItem(root, "password");
    if (!cJSON_IsString(ssid_item) || ssid_item->valuestring == nullptr ||
        std::strlen(ssid_item->valuestring) == 0) {
        cJSON_Delete(root);
        SendLine("WIFICFG:ERR:ssid_required");
        return;
    }

    std::string ssid = ssid_item->valuestring;
    std::string password;
    if (cJSON_IsString(password_item) && password_item->valuestring != nullptr) {
        password = password_item->valuestring;
    }
    cJSON_Delete(root);

    if (ssid.size() > 32 || password.size() > 64) {
        SendLine("WIFICFG:ERR:invalid_length");
        return;
    }

    auto& manager = SsidManager::GetInstance();
    const auto& list = manager.GetSsidList();
    for (int i = static_cast<int>(list.size()) - 1; i >= 0; --i) {
        if (list[i].ssid == ssid) {
            manager.RemoveSsid(i);
        }
    }
    manager.AddSsid(ssid, password);

    cJSON* result = cJSON_CreateObject();
    cJSON_AddStringToObject(result, "ssid", ssid.c_str());
    cJSON_AddBoolToObject(result, "saved", true);
    std::string result_json = JsonToString(result);
    cJSON_Delete(result);
    SendLine("WIFICFG:OK:" + result_json);

    vTaskDelay(pdMS_TO_TICKS(200));
    auto& wifi = WifiManager::GetInstance();
    if (!wifi.IsConnected()) {
        wifi.StartStation();
        SendLine("WIFICFG:CONNECTING");
    }
}

void HandleReset() {
    SsidManager::GetInstance().Clear();
    SendLine("WIFICFG:RESET_OK");
    vTaskDelay(pdMS_TO_TICKS(300));
    esp_restart();
}

void ProcessLine(const std::string& input) {
    std::string line = input;
    while (!line.empty() && (line.back() == '\r' || line.back() == ' ' || line.back() == '\t')) {
        line.pop_back();
    }
    if (line.rfind("WIFICFG:", 0) != 0 || line.size() <= 7) {
        return;
    }

    std::string rest = line.substr(7);
    std::string command = rest;
    std::string payload;
    auto colon = rest.find(':');
    if (colon != std::string::npos) {
        command = rest.substr(0, colon);
        payload = rest.substr(colon + 1);
    }

    if (command == "PING") {
        SendLine("WIFICFG:PONG");
    } else if (command == "STATUS") {
        HandleStatus();
    } else if (command == "SCAN") {
        HandleScan();
    } else if (command == "SET") {
        HandleSet(payload);
    } else if (command == "RESET") {
        HandleReset();
    } else if (command == "HELP") {
        SendLine("WIFICFG:HELP:PING|STATUS|SCAN|SET:<json>|RESET");
    } else {
        SendLine("WIFICFG:ERR:unknown_command");
    }
}

void ProvisionTask(void* arg) {
    (void)arg;

    uart_config_t config = {};
    config.baud_rate = 115200;
    config.data_bits = UART_DATA_8_BITS;
    config.parity = UART_PARITY_DISABLE;
    config.stop_bits = UART_STOP_BITS_1;
    config.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    config.source_clk = UART_SCLK_DEFAULT;

    esp_err_t err = uart_driver_install(kPort, kRxBufferSize, 0, 0, nullptr, 0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "uart_driver_install failed: %s", esp_err_to_name(err));
        vTaskDelete(nullptr);
        return;
    }
    uart_param_config(kPort, &config);

    SendLine("WIFICFG:READY");

    std::string line;
    line.reserve(kMaxLineSize);
    std::vector<uint8_t> buffer(128);

    while (true) {
        int received = uart_read_bytes(kPort, buffer.data(), buffer.size(), pdMS_TO_TICKS(100));
        if (received <= 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        for (int i = 0; i < received; ++i) {
            char c = static_cast<char>(buffer[i]);
            if (c == '\n' || c == '\r') {
                if (!line.empty()) {
                    ProcessLine(line);
                    line.clear();
                }
            } else if (line.size() < static_cast<size_t>(kMaxLineSize)) {
                line.push_back(c);
            } else {
                line.clear();
            }
        }
    }
}

}  // namespace

void SerialProvisionStart() {
    static bool started = false;
    if (started) {
        return;
    }
    started = true;
    xTaskCreate(ProvisionTask, "prov_serial", 8192, nullptr, 3, nullptr);
}

#else

void SerialProvisionStart() {}

#endif  // CONFIG_SERIAL_PROVISION_ENABLED
