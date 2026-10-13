# 独立实现结构

WPF (.NET 10) + WebView2 提供实际 Windows 窗口。TypeScript 界面由本机 FastAPI 服务提供；仅绑定 127.0.0.1 随机端口。宿主获取每次运行随机 token，认证后使用 HttpOnly SameSite cookie。API 验证 Host 和 Origin。界面关闭仅回收本实例启动的后台服务，不退出 AutoCAD。

`ModelProvider` 在 app/providers.py，分别适配 Chat Completions 和 Responses 的流式文本、工具调用、usage。用户自己填写 Base URL、模型 ID 和密钥；DPAPI 保护密钥与敏感请求头。保存配置不会发起请求。当前真实上游账号未验收，不假定任何命名供应商完全兼容。

`AgentRuntime` 在 app/runtime.py，固定任务参数和供应商快照，进行有界工具循环。工具参数通过 JSON Schema；模型不可执行任意 shell，模型结果不能直接写 CAD。外部 Codex CLI 适配器独立于 API 配置，实际登录及调用状态单独验收。

`Skill/Tool` 通过 app/skills.py 发现说明和执行器。几何由 app/geometry.py、横断面由 app/sections.py 计算，规范引用与有限条件规则由 app/rules.py 提供。导入 Markdown 不会获得操作系统执行权。第三方执行器需要代码适配、测试和启用。

`CAD Adapter` 在 app/cad.py，Windows COM 专用 STA 线程内串行操作，持有文档身份和内容指纹。模型只计算预览；用户核对目标图纸和图层后落图。创建/修改使用撤销组，回读真实对象句柄与几何。任务 ID 与输入摘要防止重复落图。只写本会话创建的图纸，不自动认领用户原图。

SQLite 保存项目、修订、任务、事件和 CAD 审计。重新启动会把未完成任务标记 interrupted，不自动重复执行。任务队列有界；当前是本机单用户软件，未做云端或百人容量承诺。

本地参考库只检索数据与出处，不执行资料附带的指令。公有源码包与本地私有资料分开构建。
