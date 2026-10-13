# 清规AI原生 CAD 源码与第三方许可

本目录的 C# 原生插件、Windows 安装器、启动器、卸载器、打包脚本和道路图标均为清规AI项目原创，按本目录 [MIT LICENSE](LICENSE) 分发。图标可由 `launcher/Build-Icon.ps1` 重新生成。原生功能版本为 0.3.0；规划计算引擎复用仓库根目录源码，不在此目录重复归档。

这些源码没有包含湘源控规的程序、反编译代码、专有图块、界面图标、许可文件或授权机制。它们也不构成湘源控规 9.0 的完整功能复刻。

AutoCAD 2025 是使用原生插件的独立前提。构建时通过开发者自己的 AutoCAD 安装引用 `AcMgd.dll`、`AcDbMgd.dll`、`AcCoreMgd.dll`、`AdWindows.dll`，引用均为 `Private=false`。Autodesk 软件及 SDK 程序集不按本项目 MIT 许可再分发，也不随本源码目录提供。

源码仓库没有内嵌 Python 运行时或第三方 wheel。完整安装包构建时会加入官方 CPython 和锁定 Python 依赖，并保留各自许可证。CPython 使用 PSF 许可；各第三方包及其捆绑库适用原有许可，项目 MIT 许可不替代它们。构建后的 `THIRD_PARTY_NOTICES.md`、`Contents/Engine/runtime/DEPENDENCIES.json` 及各包许可证共同记录这些来源。

本目录不含课程底图、用户项目、账号配置或本机安装回执。公开验收说明位于仓库 `docs/native-verification.md`；独立源码包使用者可在项目仓库查看。
