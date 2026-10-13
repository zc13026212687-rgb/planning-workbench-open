这是本项目原创的道路平面教学技能。只使用用户提供或明确标为合成的资料；不从模型记忆填入工程规范限值。

1. 先确认 units、coordinate_reference、中心线、左右宽度、路口半径、连通性层号 level（不是实际高程）和保留约束。数值缺失时保留缺项，不默认为米。width_semantics=road_boundary；ROAD_EDGE 不能自动解释为车行道或规划红线。
2. 用 RoadSpec 描述输入，line 保留端点，arc 保留圆心、半径和弧度起止角。clockwise 表示中心线方向；输出实体 ARC 一律为逆时针几何。
3. 调用 app.geometry.generate(spec)。支持独立直线、真圆弧以及同标高直路 T/X 口，含斜交。两条直路较小夹角的已验证算法范围为 30–90°，这不是规范限值。相切点反向、道路过短、Y 口、折线弯折、复合直曲线和突变宽度须由 report.errors 明示。教学案例中的 oblique-x60 / oblique-t60 可直接比较 60° 方案；完整夹角记录见 junction_angles 校核项。
4. 解释 report.checks、warnings、errors 并定位问题。几何由引擎计算；不要将自由生成的 Python/CAD 命令当作验证后的参数。
5. errors 非空时可以显示方案帮助修正，但不能导出为合格成果。通过后调用 export_dxf(result, new_path)，保留原图并使用新文件名。
6. 查看真实预览并独立检查 DXF 单位、LWPOLYLINE bulge、ARC 和图层；本机 CAD 写操作由已配对连接器执行。

相交形式未明确时设 junction_type=unknown 并保留 needs_confirmation；不能假设平交，也不能编造 level 消除冲突。方向按 segment_order，station_start 目前仅为来源元数据，不代表已有桩号标注。

验收：中心线长度、偏移宽度、圆弧半径、相切关系和路口拓扑可复算，错误输入可见；不要将教学/规划验证说成道路施工图审查。
