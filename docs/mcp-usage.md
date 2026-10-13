# 清规AI：通过 MCP 调用独立开源规划引擎

`planning_mcp.py` 是实际执行本项目计算引擎的本地 stdio 服务。它不调用湘源程序，不装载商业插件文件，不包含破解机制。Skill 负责工作说明；MCP 提供可由客户端发现和调用的结构化工具。两者可以配合使用。

本入口可配置到支持 stdio MCP 的客户端；本项目没有自动修改本机客户端配置，也没有声称已验证所有客户端。当前验收覆盖真实子进程的协议交互及实际 DXF 结果；单元测试不启动 AutoCAD。

## 准备与启动

在项目根目录创建虚拟环境并安装现有锁定依赖。示例路径请替换为实际解压目录：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -u planning_mcp.py
```

最后一行会等待 stdin 中的协议请求，没有普通交互菜单。正常使用时由 MCP 客户端启动；不应把它当作 Web 服务访问。程序不监听网络端口，也不需要 API Key。

常见的 `mcpServers` 配置形式如下。不同客户端的配置位置及外层字段可能不同，应以该客户端说明为准；`command` 和 `args` 是独立参数，不需要嵌入 shell 引号：

```json
{
  "mcpServers": {
    "planning-cad": {
      "command": "C:\\PlanningWorkbench_Open\\.venv\\Scripts\\python.exe",
      "args": ["-u", "C:\\PlanningWorkbench_Open\\planning_mcp.py"]
    }
  }
}
```

整个目录可搬迁；本入口根据自身位置加载计算引擎，不依赖开发者电脑的固定路径。安装目录改变后，更新客户端配置中的两个绝对路径。

若使用带 Python 运行时的 Windows 发行包，可将 `command` 改为该包内 `runtime/python.exe` 的完整路径；`args` 中的 `planning_mcp.py` 路径保持指向同一解压目录。本说明不自动修改任何客户端配置。

## 四个实际工具

| 工具 | 输入 | 实际结果 |
|---|---|---|
| `planning_cases` | 空对象，或 `case_id`、可选 `variant` | 返回原创合成案例列表或案例完整参数 |
| `planning_validate` | `spec` 对象 | 调用相应几何引擎，返回错误、提示、指标、边界和实体数；不写文件 |
| `planning_export` | `spec`、`out`；可选 `cad_new` 和 `confirm_cad_new` | 校核无 errors 后输出 DXF、参数、结果、QA；地块另有 CSV/JSON；可选写入独立 CAD 新图 |
| `planning_export_control_sheet` | 地块 `spec`、`parcel_id`、`out`；可选 CAD 参数 | 真实生成指定地块图则 DXF及计算结果；指标缺失保持待核实 |

支持的参数类型：道路平面可不填 `kind` 或填 `road_plan`；横断面填 `road_cross_section`；地块填 `regulatory_parcels`。道路与断面参数可通过 `planning_cases` 获取；地块参数见 `examples/regulatory-parcels.json`。经纬度不应当作米输入。是否满足规范、审批条件和真实场地要求，仍需有来源的条件和人工审查。

`out` 必须为本机绝对路径，目标目录尚不存在且其父目录已存在。无效几何、未经确认的 CAD 请求、已有目标目录都会在创建文件前拒绝。输出失败时保留已有中间文件和 `failure.json`，不假装操作已回滚。CAD 执行失败后也可能留下新图，应查看后再重试。

## 推荐操作顺序

可在已配置该服务的客户端中提出：

> 调用 planning_cases，读取 regulatory-road-plan 的 oblique-t60 参数。先 planning_validate，解释校核与适用边界。如果没有 errors，把 DXF 导出到 C:\PlanningOutputs\lesson-01；这个目录必须是新的。暂时不要操作 CAD。

确认用户已授权在 CAD 中新建图纸后，可调用：

```json
{
  "name": "planning_export",
  "arguments": {
    "spec": {
      "kind": "road_cross_section",
      "units": "m",
      "coordinate_reference": "local_cartesian",
      "synthetic": true,
      "source": "Original minimal MCP teaching example",
      "reference_elevation": 100,
      "slope_convention": "outward_rise_percent",
      "components": [
        {"id": "L1", "side": "left", "order": 0, "role": "carriageway", "width": 3.5, "slope_percent": -2},
        {"id": "R1", "side": "right", "order": 0, "role": "carriageway", "width": 3.5, "slope_percent": -2}
      ]
    },
    "out": "C:\\PlanningOutputs\\lesson-02",
    "cad_new": true,
    "confirm_cad_new": true
  }
}
```

上面的 JSON 是 `tools/call` 的 `params`，使用可直接计算的两条车行组成简例：总宽 7 米、中心高程 100 米、两侧向外坡度 -2%。这只是参数调用示范，不是完整道路断面或推荐值；课堂一般应使用 `planning_cases` 返回的完整案例。CAD 写入需要 Windows、可用的 AutoCAD ActiveX 注册及本机 COM 依赖；只创建、写入、保存本服务所建的新图，不接管现有图纸。它不会执行任意 CAD 命令，不运行调用者提供的脚本，也不会上传文件。

地块图则流程是 `planning_validate(spec)` → `planning_export(spec, out)` → `planning_export_control_sheet(spec, parcel_id="P001", out=另一个新目录)`。输入中的容积率、密度、绿地率等必须来自课堂假设或有证据的控制要求；空缺指标不自动编造。

## 协议与校验边界

实现 UTF-8、每行一个 JSON-RPC 消息的 stdio 传输；stdout 只写协议，日志写 stderr。支持 `initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`，输入流关闭即退出。协议协商支持 `2025-11-25` 与 `2025-06-18`；未知版本返回本服务支持的版本，由客户端决定兼容与否。当前工具列表不分页，不支持 HTTP、任务扩展、任意资源读取或服务端采样。

拒绝批量消息、NaN/Infinity、重复 JSON 键、非法 ID、超长/过深输入、未知工具及多余工具参数。单条输入上限 2 MiB；数组至多 10000 项，JSON 深度至多 32，递归节点至多 100000。JSON-RPC 错误返回 `error`；实际工具失败返回 `isError=true`。合法通知不回复，`tools/call` 通知不执行操作。错误输入后进程继续处理后续请求。

测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_planning_mcp.py -q
```

协议实现依据 [MCP stdio 传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[生命周期与版本协商](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) 和 [工具协议](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。本服务只声明已实现的工具能力，不代表 MCP 官方认证或全部客户端的兼容性结论。
