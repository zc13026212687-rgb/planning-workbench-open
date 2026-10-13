---
name: planning-cad-regulatory-suite
description: 通过规绘原创引擎完成有明确边界与道路宽度的控规地块生成、指标计算、单地块图则及CAD成果包。适用于规划本科教学和可追溯方案研究。
---

这是本项目的独立开源控规技能，调用确定性计算引擎。只使用用户数据或明确标为 synthetic 的例子；示例不代表大钟寺实测底图、已批红线或法定指标。

## 输入与路径

从安装入口的 `local-engine.json` 获取引擎及 Python 路径；源码使用者从本文件所在目录上溯两级定位项目根目录。先查看 `examples/regulatory-parcels.json` 和 `planning_cli.py cases`，按实际任务选择地块、道路平面或横断面参数，不混用三类 schema。填写或改动地块输入时阅读 `docs/regulatory-schema.md`。

地块输入必须声明 `kind=regulatory_parcels`、米单位与 `local_cartesian`。边界含 outer 和可选 holes；道路计算走廊明确中心线与总宽，不能把走廊自动解释为法定红线。模式为道路切分或用户地块时，分别使用引擎对应输入，保留来源与缺项。容积率、密度、绿地率、限高来自用户明确输入；未知值为空，不能根据用地名称猜测。

## 执行

通过安装入口 `scripts/run.py` 或项目 `planning_cli.py` 调用：

```text
validate --spec 已确认参数.json
generate --spec 已确认参数.json --out 新建成果目录
sheet --spec 已确认地块参数.json --parcel P001 --out 另一新目录
```

先解释 errors、warnings 和面积平衡；errors 非空时修正输入，不将预览作为合格成果导出。原生 DXF、地块 CSV/JSON、图则、参数与 QA 应指向同一参数版本。计容面积上限=净地块面积×输入容积率上限，是条件计算，不是实际建筑面积。

地块编号并不保证几何未变。已有 `attribute_geometry_bindings` 时必须保留；修改道路或边界导致绑定失配后，展示新几何并逐块核对指标归属，不能静默删掉绑定或重新绑定来消除错误。交互页提供当前几何确认；代码路径只有用户已确认归属时调用 `app.parcels.bind_attributes(spec,result)`。

已有会话授权要求 CAD 落图时加 `--cad-new`，只新建本引擎拥有的独立图纸，保留原图。根据实际回读和保存结果报告 DWG 状态；DXF 导出成功不等于 CAD 已落图。MCP 接入和四个工具见 `docs/mcp-usage.md`，其中 CAD 写入需同时设置 `cad_new` 与 `confirm_cad_new`。

## 验收边界

检查道路并集、孔洞保留、地块面积、重叠/越界、面积守恒、指标缺失与归属绑定。图则是原创 A3 教学图框，图内地块按标明比例缩放；不能回作实测底图。当前道路面、断面、地块和图则算法各有范围，不等于全流程规划合规审查。范围说明见 `docs/open-implementation.md`。

在交付中列出实际生成的文件和未解决条件。对商用软件只讨论公开功能需求与观察记录；不要复制其代码、图标、模板、注册文件或产品身份，也不把菜单数量当作已实现功能数量。
