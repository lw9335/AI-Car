import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, api } from "./api";
import type { OpsResult, Role, TraceSpan, User, WorkOrder } from "./types";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  actions?: string[];
};

const TOKEN_KEY = "roadmind_token";

const ROLE_LABEL: Record<Role, string> = {
  admin: "平台管理员",
  information_officer: "信息员",
  expert: "机务专家",
  dispatcher: "调度员",
  parts_manager: "配件管理员",
  technician: "现场工程师",
  operations: "运营负责人",
};

function can(role: Role, action: string): boolean {
  if (role === "admin") return true;
  const map: Record<string, Role[]> = {
    create: ["information_officer"],
    diagnose: ["information_officer", "technician", "expert"],
    confirm: ["expert"],
    rejectConfirm: ["expert"],
    dispatch: ["dispatcher"],
    parts: ["parts_manager"],
    start: ["technician"],
    mismatch: ["technician", "information_officer"],
    resume: ["technician", "information_officer", "expert"],
    close: ["technician"],
    closeApprove: ["expert"],
    closeReject: ["expert"],
    ops: ["operations"],
  };
  return (map[action] || []).includes(role);
}

function dieselPayload(symptom: string) {
  return {
    reporter_name: "王队长",
    reporter_phone: "13900000000",
    vehicle: {
      vin: "LVBV6PDC8SM000901",
      brand: "foton_auman",
      model: "银河 9",
      power_type: "diesel",
      model_year: 2025,
      configuration_code: "AUM-G9-YC6",
    },
    symptom,
    dtc_codes: ["P20EE"],
    telemetry: { upstream_nox_ppm: 410, downstream_nox_ppm: 355, exhaust_temp_c: 312 },
    service_mode: "oem_authorized",
    location: "佛山顺德",
  };
}

function evPayload(symptom: string) {
  return {
    reporter_name: "张师傅",
    reporter_phone: "13800000000",
    vehicle: {
      vin: "LDPGBCDC0PA000101",
      brand: "deepway",
      model: "深向星辰",
      power_type: "electric",
      model_year: 2025,
      configuration_code: "DW-HV-600",
    },
    symptom,
    dtc_codes: ["P0AA6"],
    telemetry: { insulation_kohm: 82, battery_soc: 61 },
    service_mode: "fleet_service",
    location: "佛山顺德",
  };
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(null);
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [current, setCurrent] = useState<WorkOrder | null>(null);
  const [traces, setTraces] = useState<TraceSpan[]>([]);
  const [toolCount, setToolCount] = useState(0);
  const [opsResult, setOpsResult] = useState<OpsResult | null>(null);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("roadmind123");
  const [preset, setPreset] = useState("diesel");
  const [symptom, setSymptom] = useState("重载后故障灯点亮，尿素消耗异常并偶发限扭");
  const [selectedResource, setSelectedResource] = useState("");
  const [selectedPart, setSelectedPart] = useState("");
  const [opsQuestion, setOpsQuestion] = useState("当前工单量是多少");
  const [opsDelta, setOpsDelta] = useState("10");
  const [assistantInput, setAssistantInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [assistantMessages, setAssistantMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "我是 RoadMind 交互式总控，可以协调诊断、调度、配件和运营 Agent。",
    },
  ]);
  const [assistantBusy, setAssistantBusy] = useState(false);

  const showToast = (text: string, error = false) => {
    setToast({ text, error });
    window.setTimeout(() => setToast(null), 2600);
  };

  const refresh = async (activeToken: string, preferredId?: string) => {
    const [list, toolList] = await Promise.all([
      api.listOrders(activeToken),
      api.tools(activeToken),
    ]);
    setOrders(list);
    setToolCount(toolList.length);
    const id = preferredId || current?.service_request_id;
    const selected = id ? list.find((item) => item.service_request_id === id) || null : list[0] || null;
    setCurrent(selected);
    if (selected) {
      setSelectedResource(selected.dispatch_candidates[0]?.resource_id || "");
      setSelectedPart(selected.parts_candidates[0]?.part_code || "");
      setTraces(await api.traces(activeToken, selected.service_request_id));
    } else {
      setTraces(await api.traces(activeToken));
    }
  };

  useEffect(() => {
    if (!token) return;
    api
      .me(token)
      .then(async (profile) => {
        setUser(profile);
        await refresh(token);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const pending = useMemo(() => {
    if (!current) return { dispatch: null as string | null, close: null as string | null };
    return {
      dispatch:
        current.approvals.find((a) => a.action === "dispatch.assign" && a.status === "pending")
          ?.token || null,
      close:
        current.approvals.find((a) => a.action === "service.close" && a.status === "pending")
          ?.token || null,
    };
  }, [current]);

  const onLogin = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await api.login(username, password);
      localStorage.setItem(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setUser(result.user);
      showToast(`已登录为 ${ROLE_LABEL[result.user.role]}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "登录失败", true);
    }
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setOrders([]);
    setCurrent(null);
  };

  const run = async (fn: () => Promise<WorkOrder | void>, ok = "动作已完成") => {
    if (!token) return;
    try {
      const order = await fn();
      if (order) {
        setCurrent(order);
        await refresh(token, order.service_request_id);
      } else {
        await refresh(token);
      }
      showToast(ok);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `${error.message}${error.status === 403 ? "（角色权限不足）" : ""}`
          : error instanceof Error
            ? error.message
            : "请求失败";
      showToast(message, true);
    }
  };

  const runAssistant = async (
    message: string,
    command?: string,
    args: Record<string, unknown> = {},
    confirmedActions: string[] = [],
  ) => {
    if (!token || !message.trim() || assistantBusy) return;
    setAssistantMessages((items) => [...items, { role: "user", content: message }]);
    setAssistantInput("");
    setAssistantBusy(true);
    try {
      const response = await api.assistantChat(token, {
        message,
        conversation_id: conversationId,
        confirmed_actions: confirmedActions,
        context: command ? { command, arguments: args } : {},
      });
      setConversationId(response.conversation_id);
      setAssistantMessages((items) => [
        ...items,
        {
          role: "assistant",
          content: response.content,
          actions: response.executed_actions.map((item) => item.operation),
        },
      ]);
      if (response.executed_actions.length) {
        await refresh(token, current?.service_request_id);
      }
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "总控执行失败";
      setAssistantMessages((items) => [
        ...items,
        { role: "assistant", content: `执行受阻：${messageText}` },
      ]);
    } finally {
      setAssistantBusy(false);
    }
  };

  if (!token || !user) {
    return (
      <div className="login-wrap">
        <form className="login-card form" onSubmit={onLogin}>
          <h1>RoadMind</h1>
          <p>JWT 登录后进入多角色售后协同工作台。默认演示密码 roadmind123。</p>
          <label>
            用户名
            <select value={username} onChange={(e) => setUsername(e.target.value)}>
              {Object.entries(ROLE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {value} · {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <button className="hot" type="submit">
            登录
          </button>
        </form>
        <div className={`toast${toast ? " show" : ""}${toast?.error ? " error" : ""}`}>
          {toast?.text}
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span>RM</span>
          <b>RoadMind</b>
        </div>
        <div className="user-meta">
          <span>
            {user.username} · {ROLE_LABEL[user.role]} · {user.region}
          </span>
          <button className="ghost" type="button" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <div className="grid">
        <section className="panel">
          <h2>工单列表</h2>
          <div className="list">
            {orders.length === 0 && <p className="muted">暂无工单，先创建报障。</p>}
            {orders.map((order) => (
              <button
                key={order.service_request_id}
                type="button"
                className={`list-item${current?.service_request_id === order.service_request_id ? " active" : ""}`}
                onClick={() => {
                  setCurrent(order);
                  setSelectedResource(order.dispatch_candidates[0]?.resource_id || "");
                  setSelectedPart(order.parts_candidates[0]?.part_code || "");
                  if (token) api.traces(token, order.service_request_id).then(setTraces);
                }}
              >
                <b>
                  {order.vehicle.brand} / {order.vehicle.model}
                </b>
                <span className="status">{order.status}</span>
                <div className="muted">{order.service_request_id}</div>
              </button>
            ))}
          </div>

          {can(user.role, "create") && (
            <>
              <h2 style={{ marginTop: "1.2rem" }}>创建报障</h2>
              <form
                className="form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(
                    () =>
                      api.createOrder(
                        token,
                        preset === "ev" ? evPayload(symptom) : dieselPayload(symptom),
                      ),
                    "服务请求已创建",
                  );
                }}
              >
                <label>
                  预设
                  <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    <option value="diesel">柴油 · P20EE</option>
                    <option value="ev">新能源 · P0AA6</option>
                  </select>
                </label>
                <label>
                  症状
                  <textarea
                    rows={3}
                    value={symptom}
                    onChange={(e) => setSymptom(e.target.value)}
                  />
                </label>
                <button className="hot" type="submit">
                  创建工单
                </button>
              </form>
            </>
          )}
        </section>

        <section className="panel">
          <h2>工单工作台</h2>
          {!current ? (
            <p className="muted">选择或创建一张工单开始闭环。</p>
          ) : (
            <>
              <div className="muted">
                THREAD {current.thread_id} · ROW V{current.version} · PLAN V
                {current.task_plan?.plan_version || 1}
                {current.degraded_mode ? <span className="badge-warn"> · DEGRADED</span> : null}
              </div>
              <h3 style={{ margin: "0.4rem 0" }}>
                {current.vehicle.brand} / {current.vehicle.model} ·{" "}
                {current.dtc_codes.join(",") || "待读取 DTC"}
              </h3>
              <span className="status">{current.status.toUpperCase()}</span>

              <div className="actions">
                {can(user.role, "diagnose") &&
                  ["triaged", "rediagnosis_required"].includes(current.status) && (
                    <button
                      className="action primary"
                      type="button"
                      onClick={() =>
                        void run(() => api.diagnose(token, current.service_request_id), "诊断完成")
                      }
                    >
                      运行证据诊断
                    </button>
                  )}
                {can(user.role, "confirm") && current.status === "waiting_expert" && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void run(
                        () =>
                          api.expertConfirm(token, current.service_request_id, {
                            diagnosis_id: current.diagnosis!.diagnosis_id,
                            approved: true,
                            confirmed_code: current.diagnosis!.hypotheses[0].code,
                            comment: "证据与专检结果一致",
                          }),
                        "专家已确认",
                      )
                    }
                  >
                    专家确认
                  </button>
                )}
                {can(user.role, "rejectConfirm") && current.status === "waiting_expert" && (
                  <button
                    className="action"
                    type="button"
                    onClick={() =>
                      void run(
                        () =>
                          api.expertConfirm(token, current.service_request_id, {
                            diagnosis_id: current.diagnosis!.diagnosis_id,
                            approved: false,
                            comment: "证据不足，驳回重诊",
                          }),
                        "已驳回初诊",
                      )
                    }
                  >
                    驳回初诊
                  </button>
                )}
                {can(user.role, "dispatch") &&
                  current.status === "fulfilling" &&
                  !current.selected_resource_id && (
                    <button
                      className="action"
                      type="button"
                      onClick={() =>
                        void run(
                          () =>
                            api.approveDispatch(token, current.service_request_id, {
                              resource_id: selectedResource || current.dispatch_candidates[0]?.resource_id,
                              approval_token: pending.dispatch,
                            }),
                          "已派工",
                        )
                      }
                    >
                      审批派工
                    </button>
                  )}
                {can(user.role, "parts") &&
                  current.status === "fulfilling" &&
                  !current.reserved_part_codes.length && (
                    <button
                      className="action"
                      type="button"
                      onClick={() =>
                        void run(
                          () =>
                            api.reserveParts(token, current.service_request_id, {
                              part_codes: [
                                selectedPart || current.parts_candidates[0]?.part_code,
                              ].filter(Boolean),
                              bring_both: true,
                            }),
                          "配件已预占",
                        )
                      }
                    >
                      预占配件
                    </button>
                  )}
                {can(user.role, "start") && current.status === "ready_for_service" && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void run(
                        () => api.startService(token, current.service_request_id),
                        "已开工",
                      )
                    }
                  >
                    现场开工
                  </button>
                )}
                {can(user.role, "mismatch") &&
                  ["fulfilling", "ready_for_service", "in_service"].includes(current.status) && (
                    <button
                      className="action"
                      type="button"
                      onClick={() =>
                        void run(
                          () =>
                            api.mismatch(token, current.service_request_id, {
                              actual_code: "P204F",
                              evidence: "现场喷射量测试与远程假设不一致",
                            }),
                          "已触发改诊补偿",
                        )
                      }
                    >
                      模拟改诊
                    </button>
                  )}
                {can(user.role, "resume") && current.status === "manual_takeover" && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void run(
                        () => api.resumeTakeover(token, current.service_request_id),
                        "已恢复为降级重诊",
                      )
                    }
                  >
                    人工接管恢复
                  </button>
                )}
                {can(user.role, "close") && current.status === "in_service" && (
                  <button
                    className="action"
                    type="button"
                    onClick={() =>
                      void run(
                        () =>
                          api.close(token, current.service_request_id, {
                            resolution:
                              "更换下游 NOx 传感器，完成自适应学习与路试，故障未复现。",
                            actual_part_codes: current.reserved_part_codes,
                            customer_rating: 5,
                          }),
                        "已提交结案",
                      )
                    }
                  >
                    提交结案
                  </button>
                )}
                {can(user.role, "closeApprove") && current.status === "waiting_close_approval" && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void run(
                        () =>
                          api.approveClose(token, current.service_request_id, {
                            approval_token: pending.close,
                            approved: true,
                            comment: "结案证据与质量门禁均通过",
                          }),
                        "结案已通过",
                      )
                    }
                  >
                    审批结案
                  </button>
                )}
                {can(user.role, "closeReject") && current.status === "waiting_close_approval" && (
                  <button
                    className="action"
                    type="button"
                    onClick={() =>
                      void run(
                        () =>
                          api.approveClose(token, current.service_request_id, {
                            approval_token: pending.close,
                            approved: false,
                            comment: "结案证据不足",
                          }),
                        "结案已驳回",
                      )
                    }
                  >
                    驳回结案
                  </button>
                )}
              </div>

              {current.dispatch_candidates.length > 0 && (
                <label className="form" style={{ marginBottom: "0.75rem" }}>
                  调度候选
                  <select
                    value={selectedResource}
                    onChange={(e) => setSelectedResource(e.target.value)}
                  >
                    {current.dispatch_candidates.map((item) => (
                      <option key={item.resource_id} value={item.resource_id}>
                        {item.display_name} · SCORE {item.score}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {current.parts_candidates.length > 0 && (
                <label className="form" style={{ marginBottom: "0.75rem" }}>
                  配件候选
                  <select value={selectedPart} onChange={(e) => setSelectedPart(e.target.value)}>
                    {current.parts_candidates.map((item) => (
                      <option key={item.part_code} value={item.part_code}>
                        {item.name} · {item.part_code}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <h2>证据链</h2>
              <div className="list">
                {(current.diagnosis?.evidence || []).map((item) => (
                  <div className="card" key={item.evidence_id}>
                    <b>{item.title}</b>
                    <div className="muted">
                      {item.section} · RRF {item.score}
                    </div>
                    <div>{item.excerpt}</div>
                  </div>
                ))}
                {!current.diagnosis?.evidence?.length && (
                  <p className="muted">运行诊断后展示品牌/车型/版本过滤后的证据链。</p>
                )}
              </div>
            </>
          )}
        </section>

        <section className="panel">
          <h2>交互式总控 Agent</h2>
          <div className="chat-list">
            {assistantMessages.slice(-8).map((message, index) => (
              <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
                <b>{message.role === "assistant" ? "RoadMind" : user.username}</b>
                <div>{message.content}</div>
                {message.actions?.length ? (
                  <div className="chat-actions">已执行：{message.actions.join(" · ")}</div>
                ) : null}
              </div>
            ))}
          </div>
          <form
            className="form assistant-form"
            onSubmit={(event) => {
              event.preventDefault();
              void runAssistant(assistantInput);
            }}
          >
            <textarea
              rows={3}
              value={assistantInput}
              onChange={(event) => setAssistantInput(event.target.value)}
              placeholder="告诉总控你要完成什么；配置模型后可自然语言自动选择业务 Agent。"
            />
            <button className="hot" type="submit" disabled={assistantBusy}>
              {assistantBusy ? "总控处理中…" : "发送给总控"}
            </button>
          </form>

          {current && (
            <div className="actions supervisor-actions">
              {can(user.role, "diagnose") &&
                ["triaged", "rediagnosis_required"].includes(current.status) && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void runAssistant(
                        "请让诊断 Agent 分析当前工单",
                        "diagnosis.run",
                        { order_id: current.service_request_id },
                      )
                    }
                  >
                    总控→诊断
                  </button>
                )}
              {can(user.role, "confirm") && current.status === "waiting_expert" && (
                <button
                  className="action"
                  type="button"
                  onClick={() =>
                    void runAssistant(
                      "我确认当前诊断，请总控继续编排履约",
                      "diagnosis.confirm",
                      {
                        order_id: current.service_request_id,
                        diagnosis_id: current.diagnosis!.diagnosis_id,
                        approved: true,
                        confirmed_code: current.diagnosis!.hypotheses[0].code,
                      },
                      ["diagnosis.confirm"],
                    )
                  }
                >
                  总控→确认诊断
                </button>
              )}
              {can(user.role, "dispatch") &&
                current.status === "fulfilling" &&
                !current.selected_resource_id &&
                pending.dispatch && (
                  <button
                    className="action"
                    type="button"
                    onClick={() =>
                      void runAssistant(
                        "我确认采用当前调度候选",
                        "dispatch.approve",
                        {
                          order_id: current.service_request_id,
                          resource_id:
                            selectedResource || current.dispatch_candidates[0]?.resource_id,
                          approval_token: pending.dispatch,
                        },
                        ["dispatch.approve"],
                      )
                    }
                  >
                    总控→调度
                  </button>
                )}
              {can(user.role, "parts") &&
                current.status === "fulfilling" &&
                !current.reserved_part_codes.length && (
                  <button
                    className="action"
                    type="button"
                    onClick={() =>
                      void runAssistant(
                        "我确认预留当前配件候选",
                        "parts.reserve",
                        {
                          order_id: current.service_request_id,
                          part_codes: [
                            selectedPart || current.parts_candidates[0]?.part_code,
                          ].filter(Boolean),
                          bring_both: true,
                        },
                        ["parts.reserve"],
                      )
                    }
                  >
                    总控→配件
                  </button>
                )}
              {can(user.role, "start") && current.status === "ready_for_service" && (
                <button
                  className="action primary"
                  type="button"
                  onClick={() =>
                    void runAssistant(
                      "我确认现场开工",
                      "service.start",
                      { order_id: current.service_request_id },
                      ["service.start"],
                    )
                  }
                >
                  总控→现场开工
                </button>
              )}
              {can(user.role, "close") && current.status === "in_service" && (
                <button
                  className="action"
                  type="button"
                  onClick={() =>
                    void runAssistant(
                      "维修完成，我确认提交结案",
                      "service.close",
                      {
                        order_id: current.service_request_id,
                        resolution: "完成维修、路试和故障复核，未再次复现故障。",
                        actual_part_codes: current.reserved_part_codes,
                        customer_rating: 5,
                      },
                      ["service.close"],
                    )
                  }
                >
                  总控→提交结案
                </button>
              )}
              {can(user.role, "closeApprove") &&
                current.status === "waiting_close_approval" &&
                pending.close && (
                  <button
                    className="action primary"
                    type="button"
                    onClick={() =>
                      void runAssistant(
                        "我确认结案材料完整，同意关闭工单",
                        "service.close_approve",
                        {
                          order_id: current.service_request_id,
                          approval_token: pending.close,
                          approved: true,
                          comment: "结案证据完整",
                        },
                        ["service.close_approve"],
                      )
                    }
                  >
                    总控→审批结案
                  </button>
                )}
              {can(user.role, "ops") && (
                <button
                  className="action"
                  type="button"
                  onClick={() =>
                    void runAssistant("请让运营 Agent 查询当前工单量", "operations.query", {
                      question: opsQuestion,
                    })
                  }
                >
                  总控→运营
                </button>
              )}
            </div>
          )}

          <h2 className="section-gap">Telemetry</h2>
          <div className="metrics">
            <div className="metric">
              <strong>{orders.length}</strong>
              <span>Orders</span>
            </div>
            <div className="metric">
              <strong>{traces.length}</strong>
              <span>Spans</span>
            </div>
            <div className="metric">
              <strong>{toolCount}</strong>
              <span>Tools</span>
            </div>
          </div>
          <div className="list">
            {traces.slice(-10).map((span) => (
              <div className="card" key={span.span_id}>
                <b>
                  {span.kind.toUpperCase()} · {span.name}
                </b>
                <div className="muted">
                  {span.status} · {span.span_id}
                </div>
              </div>
            ))}
          </div>

          {can(user.role, "ops") && (
            <>
              <h2 style={{ marginTop: "1rem" }}>运营问数</h2>
              <form
                className="form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void (async () => {
                    try {
                      const result = await api.opsQuery(token, {
                        question: opsQuestion,
                        scenario_delta: Number(opsDelta),
                      });
                      setOpsResult(result);
                      showToast("运营查询完成");
                    } catch (error) {
                      showToast(error instanceof Error ? error.message : "查询失败", true);
                    }
                  })();
                }}
              >
                <label>
                  问题
                  <input value={opsQuestion} onChange={(e) => setOpsQuestion(e.target.value)} />
                </label>
                <label>
                  What-if Δ
                  <input value={opsDelta} onChange={(e) => setOpsDelta(e.target.value)} />
                </label>
                <button className="hot" type="submit">
                  查询白名单指标
                </button>
              </form>
              {opsResult && <pre className="pre">{JSON.stringify(opsResult, null, 2)}</pre>}
            </>
          )}
        </section>
      </div>

      <div className={`toast${toast ? " show" : ""}${toast?.error ? " error" : ""}`}>
        {toast?.text}
      </div>
    </div>
  );
}
