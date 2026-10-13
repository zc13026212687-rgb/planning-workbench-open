使用工作台固定 section 执行器，即 app.sections.generate。CAD X 是偏距，左负右正；CAD Y 是以米计的高程。纵横比例均为 1:1。

输入 kind=road_cross_section、units=m、coordinate_reference=local_cartesian、reference_elevation，以及 slope_convention=outward_rise_percent。components 中各项包含唯一 id、side（left/right）、本侧唯一 order、正 width、明确的 slope_percent；本侧 order 从中心向外递增。负横坡表示两侧均向外下降，正值均向外上升。role 可选 sidewalk、cycleway、carriageway、median、greenbelt，仅为组成语义，不自动施加规范数值。

输入契约见 schema.json；宽度、横坡、高程的数值边界是计算范围，不是规范阈值。当前由 app.sections 自行校验，注册器不会因为这个文件存在就自动获得其他执行能力。

先核实参数来源和高程基准；缺值时要求输入，不从参考图名称推断单位，不把道路平面 left_width/right_width 当作已经分配好的断面组成。不明确的真实图纸保持 evidence gap。教学示例标 synthetic 和 teaching_parameters。

核查宽度和、高程增量 width*slope_percent/100、左右端点和连续性；errors 非空不得导出或落 CAD。通过后使用 app.sections.export_section_dxf，已有输出另存新名称。真实 CAD 写入仍走工作台显式落图操作。

首版不生成缘石高差、结构厚度、排水、土方或纵断面。输入 step_up/curb_height/thickness 会被拒绝；没有桩号—地面高程与设计条件时不得虚构纵断面。图库是证据来源，不能把第三方工程细节复制为原创或宣称已经通过规范审查。
