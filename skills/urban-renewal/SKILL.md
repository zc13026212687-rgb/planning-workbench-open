---
name: urban-renewal
description: 对比保留建筑约束下的道路支路调整方案，解释碰撞校核、净距和规划证据边界。
---

这是本项目原创的城市更新教学技能。保留建筑和禁建区由已确认 polygon 表示。缺少真实地块、产权、管线或规范资料时只提供明确标为合成的案例。

1. 使用 cases.get_case("renewal-street-adjustment") 展示两个合成方案；A 故意冲突，B 向南调整支路 20 m。20 m 是教学假设，不是优化结果。
2. 分别运行 generate(variant.spec)。核查 constraint_conflict 的侵入面积，以及 constraint_clear 的最小净距；不要只看中心线是否穿过建筑。
3. 以相同单位、坐标基准和保留约束比较 A/B。宽度、路口与既有道路连接也必须同时校核。
4. 发现冲突时显示问题并阻止合格成果导出。只有无 errors 的方案才能输出 DXF。
5. 用户要求真实方案时保留来源、版本、约束适用范围和待核实项。道路几何通过不代表消防、交通、工程、产权或规划审批已通过。

把 A/B 保存为独立项目。A 仅保留失败诊断；B 通过后才在新 CAD 文档落图。BLOCK_BOUNDARY 是研究范围示意，EXISTING_ROAD 是现状支路背景，RETAINED_OBJECT 是参与碰撞的保留建筑，RETAINED_ROAD_EDGE/PROPOSED_ROAD_EDGE 区分保留与拟调整道路，共同路口仍用 ROAD_JUNCTION。不要把背景边界当作已经实现的地块约束。
