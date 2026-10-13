# 独立技能使用

桌面与脚本共用 app 内的几何引擎、CAD 桥和规范规则。无需模型 API 即可使用。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe planning_cli.py cases
.\.venv\Scripts\python.exe planning_cli.py library '北京 控规'
.\.venv\Scripts\python.exe planning_cli.py generate --case regulatory-road-plan --out data/my-road
.\.venv\Scripts\python.exe planning_cli.py generate --case regulatory-road-plan --variant oblique-x60 --out data/my-oblique-road
.\.venv\Scripts\python.exe planning_cli.py generate --spec my-confirmed-spec.json --out data/my-drawing --cad-new
```

输出目录必须不存在，以保留历史成果。`--cad-new` 真实连接本机 AutoCAD、新建测试图、绘制、回读并保存 DWG；未加此参数仅生成 DXF、参数和报告。CAD 桥需米制；转换其他单位时必须实际缩放几何。

`cases` 的 available_variants 给出可用方案 ID；道路示例含 orthogonal、oblique-x60、oblique-t60。`--variant` 不能和 `--spec` 同用。错误方案名会阻断，不会悄悄退回默认案例。

独立技能包包含源码与技能，不含图库、API配置或个人资料。先按 requirements.lock.txt 创建 Python 环境。运行 `python install_skills.py` 把三个入口安装到当前用户 `.agents/skills`，不覆盖不同来源的同名技能。移动引擎后应重新安装；本机定位文件不进入公开源码包。新聊天可能才会发现技能，安装不是所有Agent已调用的证明。

院内规则先加入有来源的参考条目。要自动校核，应在 app/rules.py 编写明确适用范围与回归用例；未验证做法保留为参考，不升级成合规判定。当前不开放任意第三方脚本执行器；模板限于已注册的执行器。
