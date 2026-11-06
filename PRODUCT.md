# 小智 AI 控制台

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
用户明确要求 React 前端。沿用项目 Python 语音服务，新增独立标准库管理服务与 SQLite 数据存储，保持原语音链路可独立运行。

## Users
管理面向约 18–35 岁使用者的小智设备的运维和配置人员；依据用户提供的功能清单。

## Product Purpose
集中管理设备、OTA、个性化资源、模型、音色、身份记忆、视觉和交互配置，清楚区分保存、下发、执行和验证状态。

## Operating Context
现有 ESP32 固件和 Python WebSocket 语音服务，不包含管理网页。默认在本地部署；远程访问须配置管理令牌。

## Capabilities and Constraints
以《功能清单.md》为需求。硬件烧录、模型厂商账户、WakeNet 训练产物与真实声纹样本未提供；不得虚构这些验证结果。现有模型、固件和语音协议应兼容。

## Brand Commitments
保留“小智 AI”中文产品名。界面采用清晰中文；用户要求 UI 更美观。

## Evidence on Hand
源项目 backend/、device/、firmware/ 和功能清单。无真实运行遥测，不展示假运营数据。

## Product Principles
- 用真实持久化支持可操作的页面。
- 配置状态与设备执行结果分别展示。
- 共享设备记忆隔离，访客不使用个人记忆。
- 对外部服务和硬件能力明确标出接入要求。
