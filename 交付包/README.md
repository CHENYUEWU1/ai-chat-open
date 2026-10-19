# 安装辅助文件

此目录保存可选的安装辅助脚本、AstrBot 插件和 Ollama 配置示例。模型权重、AstrBot 运行时、访问凭据、个人角色卡和聊天记录不会随仓库提供。

## 使用前

1. 先阅读仓库根目录的[功能与使用指南](../功能与使用指南.md)。
2. 准备 Windows、Ollama、AstrBot 和所需模型；模型权重需单独获取。
3. 检查并调整 `model-config/` 中的本地模型路径与参数。
4. 仅安装自己需要的插件，并在 AstrBot 中自行设置 Bot Token、搜索服务等凭据。

## 目录

- `scripts/`：安装、配置和维护脚本
- `plugins/`：可选的 AstrBot 插件
- `model-config/`：Modelfile 和模板示例

不要将凭据、授权文件、个人资料或聊天记录写入这些文件后再提交。
