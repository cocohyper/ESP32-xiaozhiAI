import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  AudioLines,
  BarChart3,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Copy,
  Ellipsis,
  Eye,
  Fingerprint,
  FolderClock,
  LayoutDashboard,
  Loader2,
  LogOut,
  Menu,
  MessageCircle,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
  KeyRound,
  RotateCcw,
  AlertCircle,
  Monitor,
  FileBox,
} from "lucide-react";
import { groups, schemas, modelDefaults } from "./schema";
import { rolePresets, interactionPreset } from "./presets";
import "./style.css";

const icons = {
  device: Smartphone,
  upload: UploadCloud,
  sparkles: Sparkles,
  network: Network,
  audio: AudioLines,
  fingerprint: Fingerprint,
  eye: Eye,
  message: MessageCircle,
  chart: BarChart3,
};
const localeTime = (v) =>
  v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "—";
const number = (v) => new Intl.NumberFormat("zh-CN").format(v || 0);
const statusNames = {
  pending: "待确认",
  queued: "待终端执行",
  completed: "已完成",
  completed_local: "本地删除已完成",
  pending_integration: "待服务接入",
  failed: "失败",
  unsupported: "终端不支持",
  online: "最近有上报",
  offline: "暂无近期上报",
  needs_integration: "待接入",
  private: "仅本人可见",
  shared: "共享设备可见",
  device: "设备摄像头",
  browser: "浏览器摄像头",
};
const eventNames = {
  created: "创建配置",
  updated: "更新配置",
  deleted: "删除配置",
  config_saved: "保存配置",
  config_rollback: "配置已回滚",
  config_deleted: "删除配置",
  config_cloned: "复制配置",
  connected: "设备建立连接",
  model_fallback: "切换备用模型",
  record_created: "创建配置",
  record_updated: "更新配置",
  record_deleted: "删除配置",
  model_test_passed: "模型连接测试通过",
  ota_check: "设备检查更新",
  device_seen: "设备上报",
  command_queued: "设备指令已排队",
  command_acknowledged: "收到设备回执",
  llm_request: "模型调用",
  llm_fallback: "模型故障降级",
  device_token_rotated: "设备凭证已更新",
  memory_deleted: "用户记忆已删除",
  deletion_confirmed: "删除任务已确认",
};
function Icon({ name, ...props }) {
  const C = icons[name] || Activity;
  return <C size={19} strokeWidth={1.7} {...props} />;
}
function Badge({ children, tone = "" }) {
  return <span className={"badge " + tone}>{children}</span>;
}
function Empty({
  title = "还没有记录",
  description = "添加第一条配置，开始使用这项功能。",
  action,
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <FileBox size={29} strokeWidth={1.3} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || "overview");
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [refreshing, setRefreshing] = useState(false);
  const [token, setToken] = useState(
      sessionStorage.getItem("xz_admin_token") || "",
    ),
    [needsLogin, setNeedsLogin] = useState(false);
  const [search, setSearch] = useState(""),
    [mobile, setMobile] = useState(false),
    [editing, setEditing] = useState(null),
    [confirm, setConfirm] = useState(null),
    [toast, setToast] = useState(null),
    [help, setHelp] = useState(false),
    [camera, setCamera] = useState(false),
    [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState("all");
  const timer = useRef();
  const notify = (message, kind = "success") => {
    setToast({ message, kind });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 6000);
  };
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        ...(options.body && typeof options.body === "string"
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...options.headers,
      },
    });
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error("服务响应异常，请确认控制台服务已启动。");
    }
    if (response.status === 401) {
      setNeedsLogin(true);
      throw new Error("请输入有效的管理员令牌。");
    }
    if (!response.ok) throw new Error(body.error || "操作失败，请重试。");
    return body;
  }
  async function refresh(silent = false) {
    if (!silent) setRefreshing(true);
    try {
      const body = await api("/api/bootstrap");
      setData(body);
      setError("");
      setNeedsLogin(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }
  useEffect(() => {
    refresh();
    const id = setInterval(() => refresh(true), 30000);
    return () => clearInterval(id);
  }, [token]);
  useEffect(() => {
    const handler = () => {
      setRoute(location.hash.slice(1) || "overview");
      setSearch("");
      setFilter("all");
      setMobile(false);
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  function go(id) {
    if (location.hash === "#" + id) {
      setRoute(id);
      setMobile(false);
    } else location.hash = id;
  }
  const activeGroup =
    groups.find((g) => g.tabs.includes(route)) ||
    groups.find((g) => g.id === route);
  const collection = schemas[route] ? route : activeGroup?.tabs[0];
  const schema = schemas[collection];
  const rows = data?.collections?.[collection] || [];
  const title =
    route === "overview" ? "运行概览" : activeGroup?.label || "运行概览";
  const add = (key = collection) => setEditing({ collection: key, item: null });
  async function act(path, body, message) {
    try {
      const result = await api(path, {
        method: "POST",
        body: JSON.stringify(body || {}),
      });
      await refresh(true);
      notify(message);
      return result;
    } catch (e) {
      notify(e.message, "error");
    }
  }
  function resolveRef(key, value) {
    const targets = {
      firmware_id: "firmware",
      model_id: "models",
      fallback_model_id: "models",
      role_id: "roles",
      voice_id: "voices",
      user_id: "users",
      device_id: "devices",
      interaction_id: "interaction",
      safety_id: "safety",
      resource_id: "resources",
    };
    return (
      data?.collections?.[targets[key]]?.find(
        (x) => x.id === value || x.device_id === value,
      )?.name ||
      value ||
      "—"
    );
  }
  function display(item, key) {
    let value = item[key];
    if (collection === "events") {
      if (key === "type")
        value = eventNames[item.kind] || item.kind || item.type;
      if (key === "message")
        value =
          item.message ||
          [
            schemas[item.collection]?.singular || item.collection,
            item.name,
            item.action,
            item.status,
          ]
            .filter(Boolean)
            .join(" · ") ||
          "操作已记录";
    }
    if (key === "content" && collection === "conversations")
      return (
        <span className="conversation-cell">
          <b>用户：</b>
          {item.query || item.content || "—"}
          <br />
          <b>小智：</b>
          {item.response || "—"}
        </span>
      );
    if (key === "status" && collection === "devices") {
      const online =
        item.last_seen &&
        Date.now() - new Date(item.last_seen).getTime() < 300000;
      return (
        <Badge tone={online ? "success" : "neutral"}>
          <i />
          {online ? "最近有上报" : "等待设备上报"}
        </Badge>
      );
    }
    if (key === "enabled")
      return (
        <Badge tone={value ? "success" : "neutral"}>
          {value ? "已启用" : "未启用"}
        </Badge>
      );
    if (key === "cloned")
      return <Badge>{value ? "克隆音色" : "预设音色"}</Badge>;
    if (key === "chip")
      return (
        <span>
          {value || "—"}
          {item.flash_mb && (
            <small className="subtext">{item.flash_mb} MB Flash</small>
          )}
        </span>
      );
    if (key.endsWith("_at"))
      return <span className="time">{localeTime(value)}</span>;
    if (key.endsWith("_id"))
      return (
        <span className="truncate" title={value}>
          {resolveRef(key, value)}
        </span>
      );
    if (key === "percentage") return value == null ? "—" : value + "%";
    if (key === "status")
      return (
        <Badge
          tone={
            ["failed", "失败"].includes(value)
              ? "error"
              : ["completed", "completed_local", "通过", "已解决"].includes(
                    value,
                  )
                ? "success"
                : "neutral"
          }
        >
          {statusNames[value] || value || "待确认"}
        </Badge>
      );
    return typeof value === "object"
      ? JSON.stringify(value)
      : statusNames[value] || String(value ?? "—");
  }
  const filtered = rows
    .filter((row) =>
      JSON.stringify(row).toLowerCase().includes(search.toLowerCase()),
    )
    .filter(
      (row) =>
        filter === "all" ||
        (filter === "enabled"
          ? row.enabled === true
          : filter === "disabled"
            ? row.enabled !== true
            : row.group === filter),
    );
  const sorted = [...filtered].sort((a, b) =>
    (b.updated_at || "").localeCompare(a.updated_at || ""),
  );
  const s = data?.summary || {};
  return (
    <div className="app">
      <a
        className="skip"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        跳到主内容
      </a>
      {mobile && (
        <button
          className="scrim"
          aria-label="关闭导航"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a href="#overview" className="brand">
          <span className="brand-mark">
            <AudioLines size={25} strokeWidth={2} />
          </span>
          <span>
            小智 <b>AI</b>
            <small>让陪伴，更有个性</small>
          </span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <Monitor size={18} />
          </span>
          <span>
            我的工作空间<small>设备与体验管理</small>
          </span>
          <ChevronDown size={15} />
        </div>
        <nav aria-label="主导航">
          <a
            className={"nav-link " + (route === "overview" ? "active" : "")}
            href="#overview"
          >
            <LayoutDashboard size={19} strokeWidth={1.7} />
            运行概览
          </a>
          <p className="nav-caption">管理工作台</p>
          {groups.map((g) => (
            <a
              key={g.id}
              className={
                "nav-link " + (activeGroup?.id === g.id ? "active" : "")
              }
              href={"#" + g.tabs[0]}
            >
              <Icon name={g.icon} />
              <span>{g.label}</span>
              {g.id === "devices" && !!s.devices && <em>{s.devices}</em>}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="privacy-note">
            <ShieldCheck size={18} />
            <span>
              你的配置，由你掌控<small>本地存储 · 私密连接</small>
            </span>
          </div>
          <button className="workspace-settings" onClick={() => setHelp(true)}>
            <CircleHelp size={17} />
            接入与使用说明
            <ChevronRight size={15} />
          </button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button menu-button"
              aria-label="打开导航"
              onClick={() => setMobile(true)}
            >
              <Menu size={21} />
            </button>
            <span>工作空间</span>
            <ChevronRight size={14} />
            <b>{title}</b>
          </div>
          <div className="topbar-right">
            <span className={"connection " + (error ? "bad" : "")}>
              <i />
              {loading ? "正在连接" : error ? "连接异常" : "控制台已连接"}
            </span>
            <button
              className={"icon-button " + (refreshing ? "spinning" : "")}
              onClick={() => refresh()}
              title="刷新数据"
              aria-label="刷新数据"
              disabled={refreshing}
            >
              <RefreshCw size={17} />
            </button>
            <span className="top-divider" />
            <button
              className="profile"
              title="账户与连接"
              onClick={() => setHelp(true)}
            >
              管
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <h1>{title}</h1>
              <p>
                {route === "overview"
                  ? "从这里，照看每一台小智的日常。"
                  : activeGroup?.desc}
              </p>
            </div>
            <div className="heading-actions">
              {route === "overview" ? (
                <>
                  <span className="date-label">
                    {new Date().toLocaleDateString("zh-CN", {
                      month: "long",
                      day: "numeric",
                      weekday: "long",
                    })}
                  </span>
                  <button
                    className="button primary"
                    onClick={() => add("devices")}
                  >
                    <Plus size={17} />
                    接入设备
                  </button>
                </>
              ) : schema && !schema.readonly ? (
                <button className="button primary" onClick={() => add()}>
                  <Plus size={17} />
                  新建{schema.singular}
                </button>
              ) : null}
            </div>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <AlertCircle size={18} />
              <span>{error}</span>
              <button onClick={() => refresh()}>重新连接</button>
            </div>
          )}
          {loading ? (
            <div className="skeleton-grid" aria-label="正在加载">
              <div />
              <div />
              <div />
              <div />
            </div>
          ) : !data ? (
            <Empty
              title="等待连接控制台"
              description="请启动 Python 控制台服务，再点击重新连接。"
              action={
                <button className="button" onClick={() => refresh()}>
                  重新连接
                </button>
              }
            />
          ) : route === "overview" ? (
            <>
              <section className="welcome-banner">
                <div>
                  <span className="welcome-icon">
                    <Sparkles size={20} />
                  </span>
                  <h2>把小智，调成你喜欢的样子</h2>
                  <p>连上设备，选好声音，给每一次对话一点个性。</p>
                  <button onClick={() => go("roles")}>
                    前往交互工作室 <ArrowRight size={16} />
                  </button>
                </div>
                <div
                  className="connection-map"
                  aria-label="配置、设备与对话连接流程"
                >
                  <span className="map-node">
                    <SlidersHorizontal size={23} />
                    <small>你的设定</small>
                  </span>
                  <span className="map-line" />
                  <span className="map-center">
                    <AudioLines size={39} strokeWidth={1.7} />
                    <small>小智 AI</small>
                  </span>
                  <span className="map-line" />
                  <span className="map-node">
                    <MessageCircle size={23} />
                    <small>日常对话</small>
                  </span>
                </div>
              </section>
              <section className="stats" aria-label="运行统计">
                {[
                  {
                    label: "已接入设备",
                    value: s.devices,
                    icon: Smartphone,
                    note: `${s.online_devices || 0} 台最近 5 分钟有上报`,
                    color: "green",
                  },
                  {
                    label: "模型通道",
                    value: s.models,
                    icon: Network,
                    note: `${s.active_models || 0} 个通道已启用`,
                    color: "blue",
                  },
                  {
                    label: "对话记录",
                    value: s.conversations,
                    icon: MessageCircle,
                    note: "累计已上报对话",
                    color: "orange",
                  },
                  {
                    label: "Token 用量",
                    value: s.total_tokens,
                    icon: Activity,
                    note: "累计已上报 Token",
                    color: "violet",
                  },
                ].map((m) => (
                  <div className="stat" key={m.label}>
                    <div className="stat-top">
                      <span>{m.label}</span>
                      <m.icon size={19} className={m.color} />
                    </div>
                    <strong>{number(m.value)}</strong>
                    <small>{m.note}</small>
                  </div>
                ))}
              </section>
              <div className="overview-grid">
                <section className="panel devices-panel">
                  <div className="section-heading">
                    <h2>
                      设备动态 <span>{s.devices || 0}</span>
                    </h2>
                    <button
                      className="text-button"
                      onClick={() => go("devices")}
                    >
                      全部设备
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  {!s.devices ? (
                    <div className="device-onboarding">
                      <div className="device-outline">
                        <AudioLines size={30} />
                        <i />
                        <span />
                      </div>
                      <h3>你的第一台小智，等你接入</h3>
                      <p>
                        添加设备标识，配置 OTA 地址。
                        <br />
                        设备上线后，运行状态会出现在这里。
                      </p>
                      <button className="button" onClick={() => add("devices")}>
                        <Plus size={16} />
                        添加第一台设备
                      </button>
                      <button
                        className="text-button"
                        onClick={() => setHelp(true)}
                      >
                        查看接入步骤
                        <ArrowRight size={14} />
                      </button>
                    </div>
                  ) : (
                    <div className="device-list">
                      {data.collections.devices.slice(0, 4).map((d) => (
                        <button
                          className="device-row"
                          key={d.id}
                          onClick={() =>
                            setEditing({ collection: "devices", item: d })
                          }
                        >
                          <span className="device-avatar">
                            <Smartphone size={23} />
                          </span>
                          <span className="device-row-name">
                            <b>{d.name || d.device_id}</b>
                            <small>
                              {d.chip || "芯片待上报"} · {d.group || "默认分组"}
                            </small>
                          </span>
                          <span>
                            <Badge
                              tone={
                                d.last_seen &&
                                Date.now() - new Date(d.last_seen).getTime() <
                                  300000
                                  ? "success"
                                  : "neutral"
                              }
                            >
                              {d.last_seen &&
                              Date.now() - new Date(d.last_seen).getTime() <
                                300000
                                ? "近期有上报"
                                : "等待上报"}
                            </Badge>
                            <small className="subtext">
                              {d.firmware_version || "版本待上报"}
                            </small>
                          </span>
                          <ChevronRight size={17} />
                        </button>
                      ))}
                    </div>
                  )}
                </section>
                <section className="panel setup-panel">
                  <div className="section-heading">
                    <h2>开始配置</h2>
                    <Badge tone="success">
                      {
                        [
                          s.devices,
                          s.models,
                          data.collections.roles.length,
                        ].filter(Boolean).length
                      }{" "}
                      / 3 完成
                    </Badge>
                  </div>
                  <p className="section-description">
                    三步，建立你的专属对话体验。
                  </p>
                  {[
                    {
                      name: "连接一台设备",
                      desc: "登记设备，确认接入地址",
                      done: s.devices,
                      route: "devices",
                      icon: Smartphone,
                    },
                    {
                      name: "选一个大模型",
                      desc: "配置通道并测试连通性",
                      done: s.models,
                      route: "models",
                      icon: Network,
                    },
                    {
                      name: "定义它的个性",
                      desc: "选择角色，调整对话风格",
                      done: data.collections.roles.length,
                      route: "roles",
                      icon: Sparkles,
                    },
                  ].map((step, i) => (
                    <button
                      className="setup-step"
                      key={step.route}
                      onClick={() => go(step.route)}
                    >
                      <span
                        className={"step-icon " + (step.done ? "done" : "")}
                      >
                        {step.done ? (
                          <Check size={18} />
                        ) : (
                          <step.icon size={18} />
                        )}
                      </span>
                      <span>
                        <b>{step.name}</b>
                        <small>{step.desc}</small>
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))}
                  <div className="setup-footnote">
                    <ShieldCheck size={17} />
                    配置保存与终端生效分别记录
                  </div>
                </section>
              </div>
              <div className="overview-grid bottom-grid">
                <section className="panel">
                  <div className="section-heading">
                    <h2>最近活动</h2>
                    <button
                      className="text-button"
                      onClick={() => go("events")}
                    >
                      查看记录
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  {data.collections.events.length ? (
                    <div className="activity-list">
                      {data.collections.events.slice(0, 4).map((e) => (
                        <div className="activity-row" key={e.id}>
                          <span className="activity-dot" />
                          <span>
                            <b>
                              {eventNames[e.kind] ||
                                e.kind ||
                                e.type ||
                                "配置变更"}
                            </b>
                            <small>
                              {e.message ||
                                schemas[e.collection]?.singular ||
                                e.device_id ||
                                "控制台操作"}
                            </small>
                          </span>
                          <time>{localeTime(e.created_at)}</time>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="quiet-empty">
                      <FolderClock size={26} strokeWidth={1.4} />
                      <p>还没有运行记录</p>
                      <small>配置变更、设备上报和升级回执将自动记录。</small>
                    </div>
                  )}
                </section>
                <section className="privacy-panel">
                  <span className="privacy-heading">
                    <Fingerprint size={25} />
                    <h2>让记忆有边界</h2>
                  </span>
                  <p>
                    独立的用户记忆，清晰的可见范围。
                    <br />
                    访客模式下，不读取个人长期记忆。
                  </p>
                  <button className="text-button" onClick={() => go("users")}>
                    管理用户与记忆
                    <ArrowRight size={15} />
                  </button>
                  {s.pending_deletions > 0 && (
                    <Badge tone="warning">
                      {s.pending_deletions} 条删除申请待确认
                    </Badge>
                  )}
                </section>
              </div>
            </>
          ) : (
            <>
              {activeGroup && activeGroup.tabs.length > 1 && (
                <div
                  className="tabs"
                  role="tablist"
                  aria-label={activeGroup.label}
                >
                  {activeGroup.tabs.map((t) => (
                    <button
                      key={t}
                      role="tab"
                      aria-selected={route === t}
                      className={route === t ? "selected" : ""}
                      onClick={() => go(t)}
                    >
                      {t === "metrics" ? "运行看板" : schemas[t].label}
                    </button>
                  ))}
                </div>
              )}
              {route === "metrics" ? (
                <Metrics data={data} />
              ) : (
                schema && (
                  <>
                    {schema.hint && (
                      <div className="context-note">
                        <CircleHelp size={17} />
                        <p>{schema.hint}</p>
                        {collection === "vision" && (
                          <button
                            className="button small"
                            onClick={() => setCamera(true)}
                          >
                            <Camera size={16} />
                            摄像头预览
                          </button>
                        )}
                      </div>
                    )}
                    <section className="panel table-panel">
                      <div className="table-toolbar">
                        <div className="table-title">
                          <h2>{schema.label}</h2>
                          <span className="count">{filtered.length}</span>
                        </div>
                        <div className="table-filters">
                          <label className="search">
                            <Search size={17} />
                            <input
                              aria-label="搜索当前列表"
                              placeholder={"搜索" + schema.singular + "…"}
                              value={search}
                              onChange={(e) => setSearch(e.target.value)}
                            />
                            {search && (
                              <button
                                aria-label="清除搜索"
                                onClick={() => setSearch("")}
                              >
                                <X size={14} />
                              </button>
                            )}
                          </label>
                          {(collection === "devices" ||
                            schema.fields.some((f) => f.key === "enabled")) && (
                            <label className="filter">
                              <SlidersHorizontal size={15} />
                              <select
                                aria-label="筛选记录"
                                value={filter}
                                onChange={(e) => setFilter(e.target.value)}
                              >
                                <option value="all">
                                  全部
                                  {collection === "devices" ? "分组" : "状态"}
                                </option>
                                {collection === "devices" ? (
                                  [
                                    ...new Set(
                                      rows.map((x) => x.group).filter(Boolean),
                                    ),
                                  ].map((g) => <option key={g}>{g}</option>)
                                ) : (
                                  <>
                                    <option value="enabled">已启用</option>
                                    <option value="disabled">未启用</option>
                                  </>
                                )}
                              </select>
                            </label>
                          )}
                        </div>
                      </div>
                      {filtered.length ? (
                        <>
                          <div className="table-scroll">
                            <table>
                              <thead>
                                <tr>
                                  {schema.cols.map(([key, label]) => (
                                    <th key={key}>{label}</th>
                                  ))}
                                  <th className="actions-cell">操作</th>
                                </tr>
                              </thead>
                              <tbody>
                                {sorted.map((item) => (
                                  <tr key={item.id}>
                                    {schema.cols.map(([key]) => (
                                      <td
                                        key={key}
                                        className={
                                          key === "name" ? "name-cell" : ""
                                        }
                                      >
                                        {key === "name" ? (
                                          <button
                                            className="name-link"
                                            onClick={() =>
                                              setEditing({ collection, item })
                                            }
                                          >
                                            {display(item, key)}
                                          </button>
                                        ) : (
                                          display(item, key)
                                        )}
                                      </td>
                                    ))}
                                    <td className="actions-cell">
                                      <RowActions
                                        collection={collection}
                                        item={item}
                                        readonly={schema.readonly}
                                        onEdit={() =>
                                          setEditing({ collection, item })
                                        }
                                        onView={() =>
                                          setDetail({
                                            title: schema.singular,
                                            body: JSON.stringify(item, null, 2),
                                          })
                                        }
                                        onAction={(action) => {
                                          if (action === "delete")
                                            setConfirm({
                                              title: "删除" + schema.singular,
                                              description: `确定删除“${item.name || item.id}”吗？这项操作无法撤销。`,
                                              run: async () => {
                                                await api(
                                                  `/api/${collection}/${item.id}`,
                                                  { method: "DELETE" },
                                                );
                                                await refresh(true);
                                                notify("已删除");
                                              },
                                            });
                                          else if (action === "clone")
                                            act(
                                              `/api/${collection}/${item.id}/clone`,
                                              {},
                                              "已复制为新配置",
                                            );
                                          else if (action === "rollback")
                                            setConfirm({
                                              title: "回滚配置版本",
                                              description:
                                                "将恢复上一份已保存配置。终端状态需以重新读取和回执为准。",
                                              run: () =>
                                                act(
                                                  `/api/${collection}/${item.id}/rollback`,
                                                  {},
                                                  "后台配置已回滚",
                                                ),
                                            });
                                          else if (action === "confirm")
                                            setConfirm({
                                              title: "确认删除用户记忆",
                                              description:
                                                "将永久删除控制台中该用户的记忆和对话。第三方长期记忆需单独执行删除。",
                                              danger: true,
                                              run: () =>
                                                act(
                                                  `/api/deletion_requests/${item.id}/confirm`,
                                                  {},
                                                  "本地记忆已删除，凭证已记录",
                                                ),
                                            });
                                          else if (action === "token")
                                            setConfirm({
                                              title: "生成设备接入凭证",
                                              description:
                                                "已有凭证会立即失效。新凭证仅显示一次，请妥善保存。",
                                              run: async () => {
                                                const result = await act(
                                                  `/api/devices/${item.id}/token`,
                                                  {},
                                                  "设备凭证已生成",
                                                );
                                                if (result)
                                                  setDetail({
                                                    title:
                                                      "设备凭证 · 仅显示一次",
                                                    body: result.token,
                                                    secret: true,
                                                  });
                                              },
                                            });
                                          else
                                            act(
                                              `/api/devices/${item.id}/commands`,
                                              { type: action },
                                              "指令已排队，等待终端执行回执",
                                            );
                                        }}
                                      />
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <div className="table-footer">
                            <span>共 {filtered.length} 条记录</span>
                            <span>按最近修改排序 · 数据保存在本地</span>
                          </div>
                        </>
                      ) : (
                        <Empty
                          title={
                            search || filter !== "all"
                              ? "没有匹配的记录"
                              : "还没有" + schema.singular
                          }
                          description={
                            search || filter !== "all"
                              ? "试试其他关键词或清除筛选条件。"
                              : schema.readonly
                                ? "接入设备与服务后，上报数据会显示在这里。"
                                : `创建第一条${schema.singular}，保存你的配置。`
                          }
                          action={
                            search || filter !== "all" ? (
                              <button
                                className="button"
                                onClick={() => {
                                  setSearch("");
                                  setFilter("all");
                                }}
                              >
                                清除筛选
                              </button>
                            ) : !schema.readonly ? (
                              <button className="button" onClick={() => add()}>
                                <Plus size={16} />
                                新建{schema.singular}
                              </button>
                            ) : null
                          }
                        />
                      )}
                    </section>
                  </>
                )
              )}
            </>
          )}
          <footer className="page-footer">
            <span>小智 AI 控制台</span>
            <span>配置有迹可循，陪伴自然发生。</span>
          </footer>
        </main>
      </div>
      {editing && (
        <Editor
          key={editing.collection + (editing.item?.id || "new")}
          {...editing}
          data={data}
          api={api}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh(true);
            notify("配置已保存；设备生效以实际读取和回执为准");
          }}
        />
      )}
      {confirm && (
        <ConfirmDialog
          {...confirm}
          onClose={() => setConfirm(null)}
          notify={notify}
        />
      )}
      {needsLogin && (
        <Login
          error={error}
          onLogin={(value) => {
            sessionStorage.setItem("xz_admin_token", value);
            setError("");
            if (value === token) refresh();
            else setToken(value);
          }}
        />
      )}
      {help && (
        <Modal title="接入与使用说明" onClose={() => setHelp(false)}>
          <div className="help-content">
            <h3>连接你的设备</h3>
            <ol>
              <li>
                在设备管理中登记设备 ID，与终端 MAC / device-id 保持一致。
              </li>
              <li>
                启动原语音服务，设置 <code>XIAOZHI_CONSOLE_DB</code> 指向控制台
                SQLite 文件。
              </li>
              <li>
                将终端 OTA 地址设为语音服务的 <code>/xiaozhi/ota/</code>
                ，重启设备等待上报。
              </li>
              <li>选择并测试模型通道，绑定角色和音色，在新连接中生效。</li>
            </ol>
            <div className="context-note">
              <ShieldCheck size={18} />
              <p>
                控制台保存配置不等于设备已执行。涉及固件烧录、第三方服务和硬件测试，请查看交付文档中的功能覆盖说明。
              </p>
            </div>
            <h3>管理连接</h3>
            <p>
              本机访问默认无需令牌。对外部署时设置 CONSOLE_ADMIN_TOKEN，建议通过
              HTTPS 反向代理访问。
            </p>
            {token && (
              <button
                className="button"
                onClick={() => {
                  sessionStorage.removeItem("xz_admin_token");
                  setToken("");
                  setHelp(false);
                  setNeedsLogin(true);
                }}
              >
                <LogOut size={16} />
                退出管理连接
              </button>
            )}
          </div>
        </Modal>
      )}
      {camera && <CameraPreview onClose={() => setCamera(false)} />}
      {detail && (
        <Modal title={detail.title} onClose={() => setDetail(null)}>
          <div className="detail-body">
            {detail.secret && <p>此凭证仅显示一次，关闭后不能再次读取。</p>}
            <pre>{detail.body}</pre>
            <button
              className="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(detail.body);
                  notify("已复制");
                } catch {
                  notify("浏览器禁止复制，请手动选择文本。", "error");
                }
              }}
            >
              <Copy size={16} />
              复制
            </button>
          </div>
        </Modal>
      )}
      {toast && (
        <div className={"toast " + toast.kind} role="status">
          {toast.kind === "error" ? (
            <AlertCircle size={19} />
          ) : (
            <CheckCircle2 size={19} />
          )}
          <span>{toast.message}</span>
          <button aria-label="关闭通知" onClick={() => setToast(null)}>
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function RowActions({ collection, item, readonly, onEdit, onView, onAction }) {
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const menu = useRef();
  const menuId = `row-actions-${collection}-${item.id}`;
  return (
    <div className="row-actions">
      {readonly ? (
        <button onClick={onView}>详情</button>
      ) : (
        <button onClick={onEdit}>编辑</button>
      )}
      <div>
        <button
          className="icon-button"
          aria-label="更多操作"
          popoverTarget={menuId}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setPosition({
              left: Math.max(8, rect.right - 185),
              top: Math.max(
                8,
                Math.min(rect.bottom + 5, window.innerHeight - 280),
              ),
            });
          }}
        >
          <Ellipsis size={19} />
        </button>
        <div
          ref={menu}
          id={menuId}
          popover="auto"
          className="action-menu"
          style={position}
          onClick={(e) => {
            if (e.target.closest("button")) menu.current?.hidePopover();
          }}
        >
          <button onClick={onView}>
            <Eye size={15} />
            查看记录
          </button>
          {!readonly && (
            <>
              <button onClick={() => onAction("clone")}>
                <Copy size={15} />
                复制配置
              </button>
              {[
                "templates",
                "resources",
                "roles",
                "interaction",
                "safety",
              ].includes(collection) && (
                <button onClick={() => onAction("rollback")}>
                  <RotateCcw size={15} />
                  回滚上一版
                </button>
              )}
              {collection === "devices" && (
                <>
                  <button onClick={() => onAction("self_check")}>
                    <Activity size={15} />
                    发起设备自检
                  </button>
                  <button onClick={() => onAction("check_ota")}>
                    <UploadCloud size={15} />
                    检查设备升级
                  </button>
                  <button onClick={() => onAction("token")}>
                    <KeyRound size={15} />
                    生成接入凭证
                  </button>
                </>
              )}
              {collection === "deletion_requests" &&
                !["completed", "completed_local"].includes(item.status) && (
                  <button
                    className="danger"
                    onClick={() => onAction("confirm")}
                  >
                    <ShieldCheck size={15} />
                    确认删除记忆
                  </button>
                )}
              <button className="danger" onClick={() => onAction("delete")}>
                <Trash2 size={15} />
                删除记录
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Modal({
  title,
  onClose,
  children,
  className = "",
  dismissible = true,
}) {
  const ref = useRef();
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={"modal " + className}
      onCancel={(e) => {
        e.preventDefault();
        if (dismissible) onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        {dismissible && (
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="关闭窗口"
          >
            <X size={21} />
          </button>
        )}
      </div>
      {children}
    </dialog>
  );
}
function Editor({ collection, item, data, api, onClose, onSaved }) {
  const schema = schemas[collection];
  const preset =
    collection === "roles"
      ? rolePresets["效率助手"]
      : collection === "interaction"
        ? interactionPreset
        : {};
  const [form, setForm] = useState(() =>
    Object.fromEntries(
      schema.fields.map((f) => [
        f.key,
        item?.[f.key] ??
          (!item ? preset[f.key] : undefined) ??
          f.default ??
          (f.type === "checkbox"
            ? false
            : f.type === "select"
              ? f.options[0]
              : ""),
      ]),
    ),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [testResult, setTestResult] = useState(null),
    [upload, setUpload] = useState(
      item?.upload_id ? { id: item.upload_id } : null,
    ),
    [uploading, setUploading] = useState(false);
  function update(f, value) {
    setForm((prev) => {
      const next = { ...prev, [f.key]: value };
      if (
        f.key === "provider" &&
        collection === "models" &&
        modelDefaults[value]
      ) {
        next.base_url = modelDefaults[value][0];
        next.model_name = modelDefaults[value][1];
      }
      if (
        (f.key === "chip" || f.key === "flash_mb") &&
        collection === "resources" &&
        (next.chip !== "ESP32-S3" || Number(next.flash_mb) < 16)
      )
        next.custom_wake_word = "";
      return next;
    });
    setTestResult(null);
  }
  function payload() {
    const out = { ...form };
    for (const field of schema.fields) {
      if (field.type === "number" || field.key === "flash_mb") {
        if (out[field.key] === "") delete out[field.key];
        else out[field.key] = Number(out[field.key]);
      }
      if (field.type === "ref" && !out[field.key]) out[field.key] = "";
    }
    if (upload) out.upload_id = upload.id || upload.upload_id;
    return out;
  }
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        `/api/${collection}${item ? "/" + encodeURIComponent(item.id) : ""}`,
        { method: item ? "PUT" : "POST", body: JSON.stringify(payload()) },
      );
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setBusy(true);
    setError("");
    try {
      const result = await api("/api/models/test", {
        method: "POST",
        body: JSON.stringify({
          ...payload(),
          ...(item ? { id: item.id } : {}),
        }),
      });
      setTestResult(result);
      setForm((f) => ({ ...f, enabled: true }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function uploadFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const result = await api(
        `/api/uploads?kind=${schema.upload}&filename=${encodeURIComponent(file.name)}`,
        {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/octet-stream" },
        },
      );
      setUpload({ ...result, filename: file.name });
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }
  const customDisabled =
    collection === "resources" &&
    (form.chip !== "ESP32-S3" || Number(form.flash_mb) < 16);
  return (
    <Modal
      title={(item ? "编辑" : "新建") + schema.singular}
      onClose={onClose}
      className="editor"
    >
      <form onSubmit={submit}>
        <div className="editor-scroll">
          <p className="editor-intro">
            {schema.hint || "填写配置信息，保存后可随时调整。"}
          </p>
          {error && (
            <div className="alert error" role="alert">
              <AlertCircle size={18} />
              {error}
            </div>
          )}
          {testResult && (
            <div className="alert success">
              <CheckCircle2 size={18} />
              连接测试通过 · {testResult.latency_ms} ms
            </div>
          )}
          {collection === "roles" && (
            <div className="preset-strip">
              <span>内置 7 种角色，话术可继续编辑</span>
              <button
                type="button"
                className="button small"
                onClick={() =>
                  setForm((current) => ({
                    ...current,
                    ...rolePresets[current.category],
                  }))
                }
              >
                <Sparkles size={15} />
                套用当前角色预设
              </button>
            </div>
          )}
          <div className="form-grid">
            {schema.fields
              .filter(
                (f) =>
                  !(f.key === "custom_wake_word" && form.chip !== "ESP32-S3"),
              )
              .map((f) => (
                <label
                  className={
                    "field " +
                    (f.type === "textarea" || f.type === "checkbox"
                      ? "full"
                      : "")
                  }
                  key={f.key}
                >
                  {f.type !== "checkbox" && (
                    <span>
                      {f.label}
                      {f.required && <em>*</em>}
                    </span>
                  )}
                  {f.type === "select" || f.type === "ref" ? (
                    <select
                      value={form[f.key] ?? ""}
                      required={f.required}
                      onChange={(e) => update(f, e.target.value)}
                    >
                      {f.type === "ref" ? (
                        <>
                          <option value="">请选择{f.label}</option>
                          {(data.collections[f.collection] || []).map((x) => (
                            <option key={x.id} value={x.id}>
                              {x.name || x.id}
                            </option>
                          ))}
                        </>
                      ) : (
                        f.options.map((o) => <option key={o}>{o}</option>)
                      )}
                    </select>
                  ) : f.type === "image" ? (
                    <ImageField
                      value={form[f.key]}
                      label={f.label}
                      api={api}
                      onChange={(value) => update(f, value)}
                    />
                  ) : f.type === "textarea" ? (
                    <textarea
                      rows={3}
                      value={form[f.key] || ""}
                      onChange={(e) => update(f, e.target.value)}
                      placeholder={f.placeholder}
                    />
                  ) : f.type === "checkbox" ? (
                    <span className="checkbox-line">
                      <input
                        type="checkbox"
                        checked={!!form[f.key]}
                        onChange={(e) => update(f, e.target.checked)}
                      />
                      <span>{f.label}</span>
                    </span>
                  ) : (
                    <input
                      type={f.type}
                      value={form[f.key] ?? ""}
                      onChange={(e) => update(f, e.target.value)}
                      required={f.required}
                      min={f.min}
                      max={f.max}
                      step={f.type === "number" ? "any" : undefined}
                      disabled={f.key === "custom_wake_word" && customDisabled}
                      autoComplete={
                        f.type === "password" ? "new-password" : "off"
                      }
                      placeholder={
                        f.type === "password" && item?.api_key_configured
                          ? "已保存，留空保留"
                          : f.placeholder
                      }
                      maxLength={f.type === "text" ? 2000 : undefined}
                    />
                  )}{" "}
                  {f.hint && <small>{f.hint}</small>}
                  {f.key === "custom_wake_word" && customDisabled && (
                    <small>自定义唤醒词需要至少 16MB Flash。</small>
                  )}
                </label>
              ))}
          </div>
          {schema.upload && (
            <div className="upload-section">
              <h3>
                {schema.upload === "firmware"
                  ? "上传应用固件"
                  : "上传已生成的资源包"}
              </h3>
              <label className="upload-drop">
                <UploadCloud size={25} />
                <span>
                  {uploading
                    ? "正在上传…"
                    : upload
                      ? upload.filename || "已关联上传文件，可重新选择"
                      : "选择 .bin 文件"}
                </span>
                <small>最大 32 MB · 上传后验证格式并计算 SHA-256</small>
                <input
                  aria-label="选择上传文件"
                  type="file"
                  accept=".bin"
                  disabled={uploading}
                  onChange={uploadFile}
                />
              </label>
              {upload && (
                <div className="upload-success">
                  <CheckCircle2 size={15} />
                  {upload.filename || "已保存文件"}
                  {upload.sha256 && (
                    <code title={upload.sha256}>
                      SHA256 {upload.sha256.slice(0, 16)}…
                    </code>
                  )}
                </div>
              )}
            </div>
          )}
          {collection === "voices" &&
            form.sample_url &&
            /^https?:\/\//.test(form.sample_url) && (
              <div className="audio-preview">
                <h3>试听音频</h3>
                <audio controls preload="none" src={form.sample_url}>
                  浏览器不支持音频播放
                </audio>
                <p>音频由提供的地址加载，请确认与当前音色对应。</p>
              </div>
            )}
        </div>
        <div className="editor-footer">
          {collection === "models" && (
            <button
              type="button"
              className="button"
              onClick={test}
              disabled={busy}
            >
              <Activity size={16} />
              测试连接
            </button>
          )}
          <span className="flex-spacer" />
          <button type="button" className="button ghost" onClick={onClose}>
            取消
          </button>
          <button className="button primary" disabled={busy || uploading}>
            {busy ? (
              <Loader2 size={16} className="spinning" />
            ) : (
              <Check size={16} />
            )}
            保存配置
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ImageField({ value, label, api, onChange }) {
  const [preview, setPreview] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let disposed = false,
      url;
    setPreview("");
    if (value?.startsWith("/api/downloads/")) {
      const token = sessionStorage.getItem("xz_admin_token");
      fetch(value, {
        headers: token ? { Authorization: "Bearer " + token } : {},
      })
        .then((r) => {
          if (!r.ok) throw new Error("图片加载失败");
          return r.blob();
        })
        .then((blob) => {
          if (disposed) return;
          url = URL.createObjectURL(blob);
          setPreview(url);
        })
        .catch(() => setError("图片暂不可预览"));
    }
    return () => {
      disposed = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [value]);
  async function upload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await api(
        "/api/uploads?kind=resources&filename=" + encodeURIComponent(file.name),
        {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/octet-stream" },
        },
      );
      onChange(result.download_url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="image-field">
      {preview ? (
        <img src={preview} alt={label + "预览"} />
      ) : (
        <span className="image-placeholder">
          <Sparkles size={24} />
        </span>
      )}
      <span className="image-field-controls">
        <input
          type="file"
          aria-label={"上传" + label}
          accept="image/png,image/gif"
          disabled={busy}
          onChange={upload}
        />
        <small>
          {busy ? "正在上传并校验…" : "PNG / GIF · 最大 1024 × 1024"}
        </small>
        {value && (
          <button
            type="button"
            className="text-button"
            onClick={() => onChange("")}
          >
            移除图片
          </button>
        )}
        {error && (
          <small role="alert" className="field-error">
            {error}
          </small>
        )}
      </span>
    </span>
  );
}

function ConfirmDialog({ title, description, run, onClose, notify, danger }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <div className="confirm-body">
        <p>{description}</p>
        {error && <div className="alert error">{error}</div>}
      </div>
      <div className="editor-footer">
        <span className="flex-spacer" />
        <button className="button" onClick={onClose}>
          取消
        </button>
        <button
          className={"button " + (danger ? "danger-solid" : "primary")}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await run();
              onClose();
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "处理中…" : "确认操作"}
        </button>
      </div>
    </Modal>
  );
}
function Login({ onLogin, error }) {
  const [value, setValue] = useState("");
  return (
    <Modal title="连接管理控制台" dismissible={false}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onLogin(value);
        }}
      >
        <div className="confirm-body">
          <p>此服务启用了管理员认证，请输入部署时设置的管理令牌。</p>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <label className="field">
            <span>管理员令牌</span>
            <input
              type="password"
              value={value}
              autoComplete="current-password"
              onChange={(e) => setValue(e.target.value)}
              required
            />
          </label>
        </div>
        <div className="editor-footer">
          <button className="button primary">连接控制台</button>
        </div>
      </form>
    </Modal>
  );
}
function CameraPreview({ onClose }) {
  const ref = useRef(),
    stream = useRef();
  const [error, setError] = useState(""),
    [active, setActive] = useState(false);
  useEffect(
    () => () => stream.current?.getTracks().forEach((t) => t.stop()),
    [],
  );
  async function start() {
    try {
      if (!navigator.mediaDevices)
        throw new Error("摄像头需要 HTTPS 或 localhost 安全环境。");
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
        audio: false,
      });
      ref.current.srcObject = stream.current;
      setActive(true);
      setError("");
    } catch (e) {
      setError(
        e.name === "NotAllowedError"
          ? "未获得摄像头权限，请在浏览器设置中允许后重试。"
          : e.message,
      );
    }
  }
  return (
    <Modal title="浏览器摄像头预览" onClose={onClose}>
      <div className="camera-body">
        <video ref={ref} autoPlay muted playsInline />
        <p>图像仅在本机预览，不上传到服务器。远程 MCP 视觉通道需单独配置。</p>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        <button
          className="button primary"
          onClick={
            active
              ? () => {
                  stream.current?.getTracks().forEach((t) => t.stop());
                  setActive(false);
                }
              : start
          }
        >
          <Camera size={17} />
          {active ? "关闭摄像头" : "开启摄像头"}
        </button>
      </div>
    </Modal>
  );
}
function Metrics({ data }) {
  const events = data.collections.events.filter((e) =>
    ["telemetry", "llm_request", "conversation"].includes(e.kind),
  );
  const [device, setDevice] = useState(""),
    [days, setDays] = useState("7");
  const filtered = events.filter(
    (e) =>
      (!device || e.device_id === device) &&
      (days === "all" ||
        new Date(e.created_at).getTime() >=
          Date.now() - Number(days) * 86400000),
  );
  const segments = [
    ["asr_ms", "ASR 识别"],
    ["llm_first_token_ms", "LLM 首 Token"],
    ["llm_sentence_ms", "LLM 成句"],
    ["tts_first_frame_ms", "TTS 首帧"],
    ["latency_ms", "端到端"],
  ];
  const totals = {};
  filtered.forEach((e) => {
    const model = e.model_name || e.model || "未标记模型";
    if (typeof e.total_tokens === "number")
      totals[model] = (totals[model] || 0) + e.total_tokens;
  });
  return (
    <>
      <div className="metrics-filters">
        <label className="filter">
          <Smartphone size={16} />
          <select
            aria-label="看板设备筛选"
            value={device}
            onChange={(e) => setDevice(e.target.value)}
          >
            <option value="">全部设备</option>
            {data.collections.devices.map((d) => (
              <option key={d.id} value={d.device_id || d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="filter">
          <FolderClock size={16} />
          <select
            aria-label="看板时间范围"
            value={days}
            onChange={(e) => setDays(e.target.value)}
          >
            <option value="1">最近 24 小时</option>
            <option value="7">最近 7 天</option>
            <option value="30">最近 30 天</option>
            <option value="all">全部时间</option>
          </select>
        </label>
        <span>{filtered.length} 条真实遥测事件</span>
      </div>
      <div className="metrics-grid">
        <section className="panel">
          <div className="section-heading">
            <h2>分段响应时延</h2>
            <Badge>平均值 · ms</Badge>
          </div>
          <p className="section-description">
            仅统计实际收到的分段耗时，不使用参考区间代替实测。
          </p>
          <div className="latency-list">
            {segments.map(([key, label]) => {
              const values = filtered
                .map(
                  (e) =>
                    e[key] ??
                    e.metrics?.[key] ??
                    (key === "llm_first_token_ms"
                      ? e.first_token_ms
                      : undefined),
                )
                .filter((v) => typeof v === "number");
              const avg = values.length
                ? Math.round(values.reduce((a, b) => a + b, 0) / values.length)
                : null;
              return (
                <div className="latency-row" key={key}>
                  <span>{label}</span>
                  <div className="latency-track">
                    {avg !== null && (
                      <i
                        style={{
                          width: Math.min((avg / 2500) * 100, 100) + "%",
                        }}
                      />
                    )}
                  </div>
                  <b>{avg ?? "—"}</b>
                  <small>
                    {values.length ? values.length + " 次" : "暂无上报"}
                  </small>
                </div>
              );
            })}
          </div>
        </section>
        <section className="panel">
          <div className="section-heading">
            <h2>模型 Token 用量</h2>
          </div>
          {Object.keys(totals).length ? (
            <div className="usage-list">
              {Object.entries(totals).map(([name, value]) => (
                <div key={name}>
                  <span>{name}</span>
                  <b>{number(value)}</b>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="等待 Token 数据"
              description="模型调用上报后，在这里比较各通道用量。"
            />
          )}
        </section>
      </div>
      <section className="panel quality-panel">
        <div className="section-heading">
          <h2>交互质量</h2>
          <Badge>按上报事件统计</Badge>
        </div>
        <div className="quality-grid">
          {[
            ["wake_success", "唤醒成功率"],
            ["false_wake", "误唤醒率"],
            ["interrupt_success", "打断成功率"],
            ["clarification", "澄清率"],
            ["fallback", "兜底率"],
            ["unsubscribe", "提醒退订率"],
            ["negative_feedback", "差评率"],
            ["satisfied", "满意度"],
          ].map(([key, label]) => {
            const samples = filtered.filter((e) => typeof e[key] === "boolean");
            return (
              <div key={key}>
                <span>{label}</span>
                <b>
                  {samples.length
                    ? Math.round(
                        (samples.filter((e) => e[key]).length /
                          samples.length) *
                          100,
                      ) + "%"
                    : "—"}
                </b>
                <small>
                  {samples.length
                    ? samples.length + " 条样本"
                    : "等待终端 / 服务端上报"}
                </small>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
