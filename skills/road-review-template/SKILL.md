---
name: road-review-template
description: 对明确单位与中心线的道路平面作教师教学校核，通过固定几何执行器生成可复核结果。
---

这是工作台可导入的本地 manifest 模板。目录保留 manifest.json、SKILL.md、schema.json，放在工作台 skills 下，登记后默认禁用；在技能界面先执行“几何试运行”，通过后再显式启用。复制新模板时同时修改目录名、manifest id、frontmatter name，避免与内置 ID 冲突。

执行器为现有 geometry，不运行该目录下任意 Python、Shell 或网页脚本。permissions 必须属于已登记白名单，并包含执行器所需权限，不能扩大运行时工具范围。manifest 的 input_schema 在试运行和任务执行前以 JSON Schema Draft 2020-12 校验；schema.json 必须留在技能目录内，引用仅允许文档内部的 # 路径。几何引擎随后独立校验工程参数与实体。不要声称导入后已经拥有新的几何算法。

可选 dependencies 是技能目录内相对文件路径数组，注册器只检查存在并计算内容哈希，不导入其中代码。manifest、SKILL.md、Schema 或声明依赖改变后，旧诊断失效，须重新试运行并启用。诊断使用内置合成道路案例，只在内存生成真实几何，不调用模型、不写 CAD；通过不代表真实工程或规范已验收。实际几何任务使用各自成果目录，CAD 写入由独立 STA 通道串行处理，技能自身不声明虚构的资源锁。

先读项目 spec 和来源。宽度语义 road_boundary 是中心线到道路边界的左右偏距，不自动等于车行道宽度或规划红线。方向为 segment_order；交叉形式未确认时设 junction_type=unknown 并保留 needs_confirmation。依据教师作业要求说明修改原因，每次保存独立版本。

几何计算只走既有 calculate_roads 或确定性任务。对更新案例同时检查道路包络与 preserve/no_build 多边形；出错结果只用于诊断，不写 CAD、不导出成品。通过后记录单位、源参数、报告、修改前后变化及可编辑 DXF；真实 CAD 写入由工作台落图步骤完成。

读取 schema.json 可核对输入字段。详尽示例见 ../../docs/teaching-guide.md；算法边界见 ../../docs/geometry-limitations.md。不得把教学数值升级为规范阈值。
