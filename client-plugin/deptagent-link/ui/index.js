/**
 * deptagent-link 员工面板 — frontend（runtime-loaded plugin module，SPEC 3.8）。
 *
 * 由 QwenPaw console 经 usePluginLoader 动态加载（manifest entry.frontend，
 * 同源 Blob URL + dynamic import）。React/antd 取自 window.QwenPaw.host，
 * 本 bundle 无构建步骤、无第三方依赖。
 *
 * 数据层走插件后端 PawApp 路由 /api/deptagent-link/*（panel.py）；
 * 鉴权由宿主 /api 全局中间件 + Bearer host.getApiToken() 处理。
 *
 * 注册路径 /plugin/deptagent-link/panel（非 /apps/ 前缀）→ console
 * 设置区 Plugins 分组（hostExternals registerRoutes shim 语义），
 * 即「QwenPaw 设置内一页」（SPEC 3.8）。
 */
(function () {
  "use strict";
  var QwenPaw = window.QwenPaw;
  if (!QwenPaw || !QwenPaw.host || !QwenPaw.registerRoutes) {
    console.error("[deptagent-link] window.QwenPaw not ready — cannot register.");
    return;
  }

  var host = QwenPaw.host;
  var React = host.React;
  var antd = host.antd;
  var h = React.createElement;

  var Alert = antd.Alert;
  var Badge = antd.Badge;
  var Button = antd.Button;
  var Card = antd.Card;
  var Descriptions = antd.Descriptions;
  var Input = antd.Input;
  var Modal = antd.Modal;
  var Space = antd.Space;
  var Spin = antd.Spin;
  var Statistic = antd.Statistic;
  var Switch = antd.Switch;
  var Table = antd.Table;
  var Typography = antd.Typography;
  var message = antd.message;
  var Text = Typography.Text;
  var Password = Input.Password;

  var API_BASE = "/deptagent-link";
  var PAUSE_NOTE =
    "暂停后台账与用量停止上报，心跳保持并携带暂停状态（管理端显示“已暂停”而非离线）；恢复后自动续报。";

  // ── API helpers（同 agent-kanban 官方样例模式）────────────────────────
  function apiFetch(path, opts) {
    opts = opts || {};
    var url = host.getApiUrl(API_BASE + path);
    var token = host.getApiToken ? host.getApiToken() : "";
    var headers = opts.headers || {};
    headers["Content-Type"] = "application/json";
    if (token) headers["Authorization"] = "Bearer " + token;
    return fetch(url, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    }).then(function (res) {
      if (res.status === 204) return null;
      return res.json().then(function (data) {
        if (!res.ok) {
          var err =
            (data && data.error && data.error.message) || "HTTP " + res.status;
          throw new Error(err);
        }
        return data;
      });
    });
  }

  function fmtTime(iso) {
    if (!iso) return "从未";
    var d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
  }

  function uploadLight(upload, paused, collect) {
    if (paused) return { color: "blue", text: "已暂停上报（心跳保持）" };
    // 采集层降级（3.7）：格式不兼容 → 黄灯（仅心跳上报中）
    if (collect && collect.degraded)
      return { color: "orange", text: "数据格式不兼容，已降级为仅心跳上报" };
    var s = (upload && upload.state) || "idle";
    if (s === "ok") return { color: "green", text: "上报正常" };
    if (s === "error") return { color: "orange", text: "上报异常，自动重试中" };
    if (s === "revoked" || s === "invalid")
      return { color: "red", text: "设备令牌已失效，请重新绑定" };
    return { color: "default", text: "等待首次上报" };
  }

  // ── 绑定表单（未绑定 / 重新绑定后，SPEC 3.5 输码）────────────────────
  var BIND_FIELDS = [
    ["server_url", "服务器地址", "https://dept.example.com", false],
    ["invite_code", "邀请码", "DA-XXXXXXXX", false],
    ["employee_no", "工号", "M102", false],
    ["name", "姓名（首次绑定时建档用，可选）", "张三", false],
    ["password", "密码（老员工校验用，可选）", "", true],
    ["device_name", "本机名称（可选，默认主机名）", "", false],
  ];

  function BindForm(props) {
    var onBound = props.onBound;
    var valuesState = React.useState({});
    var values = valuesState[0];
    var setValues = valuesState[1];
    var busyState = React.useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];

    function set(field, v) {
      setValues(function (prev) {
        var next = Object.assign({}, prev);
        next[field] = v;
        return next;
      });
    }

    function submit() {
      if (!values.server_url || !values.invite_code || !values.employee_no) {
        message.warning("请填写服务器地址、邀请码与工号");
        return;
      }
      setBusy(true);
      apiFetch("/bind", { method: "POST", body: values })
        .then(function () {
          message.success("绑定成功，正在后台进行首次全量上报…");
          onBound();
        })
        .catch(function (e) {
          message.error("绑定失败：" + e.message);
        })
        .finally(function () {
          setBusy(false);
        });
    }

    return h(
      Card,
      { title: "设备绑定（输邀请码接入部门智通）", size: "small", style: { marginBottom: 16 } },
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px", marginBottom: 16 } },
        BIND_FIELDS.map(function (f) {
          return h(
            "div",
            { key: f[0] },
            h(
              "div",
              { style: { marginBottom: 4, color: "#6b7280", fontSize: 12 } },
              f[1]
            ),
            f[3]
              ? h(Password, {
                  value: values[f[0]] || "",
                  onChange: function (e) {
                    set(f[0], e.target.value);
                  },
                  placeholder: f[2],
                })
              : h(Input, {
                  value: values[f[0]] || "",
                  onChange: function (e) {
                    set(f[0], e.target.value);
                  },
                  placeholder: f[2],
                })
          );
        })
      ),
      h(Button, { type: "primary", loading: busy, onClick: submit }, "绑定本机")
    );
  }

  // ── 今日已上报明细（SPEC 3.4 透明展示）────────────────────────────────
  var USAGE_COLUMNS = [
    {
      title: "智能体",
      dataIndex: "agent_key",
      key: "agent_key",
      render: function (v) {
        return v || "未归属";
      },
    },
    { title: "厂商", dataIndex: "provider_id", key: "provider_id" },
    { title: "模型", dataIndex: "model", key: "model" },
    {
      title: "Tokens",
      key: "tokens",
      align: "right",
      render: function (_, r) {
        var total =
          (r.prompt_tokens || 0) +
          (r.completion_tokens || 0) +
          (r.cache_read_tokens || 0) +
          (r.cache_write_tokens || 0);
        return total.toLocaleString();
      },
    },
    { title: "调用次数", dataIndex: "call_count", key: "call_count", align: "right" },
  ];

  function usageRowKey(r) {
    return (r.agent_key || "-") + "/" + (r.provider_id || "") + "/" + (r.model || "");
  }

  // ── 主面板 ────────────────────────────────────────────────────────────
  function DeptAgentPanel() {
    var dataState = React.useState(null);
    var data = dataState[0];
    var setData = dataState[1];
    var errState = React.useState(null);
    var error = errState[0];
    var setError = errState[1];
    var busyState = React.useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];

    var load = React.useCallback(function () {
      apiFetch("/status")
        .then(function (d) {
          setData(d);
          setError(null);
        })
        .catch(function (e) {
          setError(e.message);
        });
    }, []);

    React.useEffect(function () {
      load();
      var timer = setInterval(load, 30000);
      return function () {
        clearInterval(timer);
      };
    }, [load]);

    function syncNow() {
      setBusy(true);
      apiFetch("/sync", { method: "POST" })
        .then(function (res) {
          var results = res.results || {};
          var failed = Object.keys(results).filter(function (k) {
            return String(results[k]).indexOf("failed") === 0;
          });
          if (failed.length) {
            message.warning(
              "部分通道失败：" +
                failed
                  .map(function (k) {
                    return k + "（" + results[k] + "）";
                  })
                  .join("；")
            );
          } else {
            message.success(
              "同步完成：" +
                Object.keys(results)
                  .map(function (k) {
                    return k + " " + results[k];
                  })
                  .join("，")
            );
          }
          load();
        })
        .catch(function (e) {
          message.error("同步失败：" + e.message);
        })
        .finally(function () {
          setBusy(false);
        });
    }

    function togglePause(checked) {
      apiFetch("/pause", { method: "POST", body: { paused: checked } })
        .then(function (res) {
          if (checked) {
            message.info("已暂停本机上报。" + PAUSE_NOTE);
          } else {
            message.success("已恢复本机上报，下个周期自动续报");
          }
          load();
        })
        .catch(function (e) {
          message.error("操作失败：" + e.message);
        });
    }

    function rebind() {
      Modal.confirm({
        title: "重新绑定",
        content:
          "将清除本机绑定与设备令牌；之后需要重新输入邀请码完成绑定。确定继续？",
        okText: "清除并重新绑定",
        okType: "danger",
        cancelText: "取消",
        onOk: function () {
          return apiFetch("/rebind", { method: "POST" }).then(function () {
            message.success("已清除绑定，请重新输入邀请码");
            load();
          });
        },
      });
    }

    function exportDiagnostics() {
      apiFetch("/diagnostics")
        .then(function (diag) {
          var blob = new Blob([JSON.stringify(diag, null, 2)], {
            type: "application/json",
          });
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download =
            "deptagent-diagnostics-" +
            new Date().toISOString().slice(0, 10) +
            ".json";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          message.success("诊断日志已导出（不含设备令牌）");
        })
        .catch(function (e) {
          message.error("导出失败：" + e.message);
        });
    }

    if (error) {
      return h(
        Alert,
        {
          type: "error",
          showIcon: true,
          message: "面板数据加载失败",
          description: error,
        }
      );
    }
    if (!data) {
      return h(
        "div",
        { style: { padding: 48, textAlign: "center" } },
        h(Spin, { tip: "加载面板数据…" })
      );
    }

    var light = uploadLight(data.upload, data.paused, data.collect);
    var today = data.today || {};
    var usageRows = today.usage_rows || [];

    return h(
      "div",
      { style: { maxWidth: 920, margin: "0 auto", padding: "8px 4px" } },
      // 顶部常驻隐私承诺（SPEC 3.4 红线）
      h(Alert, {
        type: "success",
        showIcon: true,
        style: { marginBottom: 16 },
        message: "隐私承诺",
        description:
          "本插件只上报设备标识、版本与用量计数，不上传对话内容、记忆、文件、提示词文本与剪贴板；你可随时在下方暂停本机上报。",
      }),
      !data.binding
        ? h(BindForm, { onBound: load })
        : h(
            Card,
            { title: "绑定信息", size: "small", style: { marginBottom: 16 } },
            h(
              Descriptions,
              { size: "small", column: 3, bordered: true },
              h(Descriptions.Item, { label: "工号" }, data.binding.employee_no || "—"),
              h(Descriptions.Item, { label: "服务器" }, data.binding.server_url || "—"),
              h(
                Descriptions.Item,
                { label: "绑定时间" },
                fmtTime(data.binding.bound_at)
              ),
              h(
                Descriptions.Item,
                { label: "上报状态", span: 2 },
                h(
                  "span",
                  null,
                  h(Badge, {
                    status: light.color,
                    text:
                      light.text +
                      (data.upload.detail ? "（" + data.upload.detail + "）" : ""),
                  })
                )
              ),
              h(
                Descriptions.Item,
                { label: "最近成功上报" },
                fmtTime(data.upload.last_ok)
              )
            )
          ),
      // 三通道信号灯（SPEC 3.8 状态卡：三通道 + 最近执行时间）
      h(
        Card,
        { title: "遥测通道", size: "small", style: { marginBottom: 16 } },
        h(Table, {
          size: "small",
          pagination: false,
          rowKey: "name",
          dataSource: data.channels || [],
          columns: [
            { title: "通道", dataIndex: "label", key: "label" },
            {
              title: "信号灯",
              key: "light",
              width: 220,
              render: function () {
                return h(Badge, { status: light.color, text: light.text });
              },
            },
            {
              title: "周期",
              key: "interval",
              width: 90,
              render: function (_, r) {
                return "每 " + r.interval_min + " 分钟";
              },
            },
            {
              title: "最近执行",
              key: "last_run",
              render: function (_, r) {
                return fmtTime(r.last_run);
              },
            },
          ],
        })
      ),
      // 今日已上报内容（SPEC 3.4 透明展示 + 3.8 状态卡今日 token 数）
      h(
        Card,
        {
          title: "今日已上报（" + (today.date || "—") + "）",
          size: "small",
          style: { marginBottom: 16 },
        },
        h(
          "div",
          { style: { display: "flex", gap: 40, marginBottom: 12, flexWrap: "wrap" } },
          h(Statistic, {
            title: "今日已上报 Tokens",
            value: today.usage_tokens || 0,
          }),
          h(Statistic, {
            title: "上报的智能体数",
            value:
              today.agents_count === undefined ? "—" : today.agents_count,
          }),
          h(Statistic, {
            title: "最近用量上报",
            value: fmtTime(today.usage_sent_at),
          })
        ),
        usageRows.length
          ? h(Table, {
              size: "small",
              pagination: false,
              rowKey: usageRowKey,
              columns: USAGE_COLUMNS,
              dataSource: usageRows,
            })
          : h(
              Text,
              { type: "secondary" },
              "今日暂无已上报的用量数据（本地产生新用量后，下个周期自动上报）"
            )
      ),
      // 操作四件（SPEC 3.8）
      h(
        Card,
        { title: "操作", size: "small" },
        h(
          Space,
          { wrap: true, size: "middle" },
          h(
            Button,
            { type: "primary", loading: busy, onClick: syncNow },
            "立即同步"
          ),
          h(
            "span",
            null,
            h(Switch, {
              checked: !!data.paused,
              onChange: togglePause,
              checkedChildren: "已暂停",
              unCheckedChildren: "正常上报",
            }),
            h(
              Text,
              { type: "secondary", style: { marginLeft: 8 } },
              "暂停本机上报（透明退出权）"
            )
          ),
          data.binding
            ? h(Button, { danger: true, onClick: rebind }, "重新绑定")
            : null,
          h(Button, { onClick: exportDiagnostics }, "导出诊断日志")
        ),
        h(
          "div",
          { style: { marginTop: 12, color: "#9ca3af", fontSize: 12 } },
          PAUSE_NOTE
        )
      )
    );
  }

  // ── 注册（非 /apps/ 前缀 → 设置区 Plugins 分组，SPEC 3.8）────────────
  QwenPaw.registerRoutes("deptagent-link", [
    {
      path: "/plugin/deptagent-link/panel",
      component: DeptAgentPanel,
      label: "部门智通",
      icon: "🛰️",
      title: "部门智通 · 员工面板",
      priority: 10,
    },
  ]);
  console.info("[deptagent-link] registered route /plugin/deptagent-link/panel");
})();
