# macOS 安装

使用与 Windows、Linux 相同的插件 ZIP 和 MCP wheel。需要 Blender 4.2+；MCP 端另需 Python 3.10+。macOS 尚未实机验证。

## Blender 插件

在 Blender **偏好设置 → 插件 → 从磁盘安装** 中选择 `facetcue-0.5.2.zip`，启用 **FacetCue for Blender**，再打开 **3D 视口 → N → FacetCue for Blender**。ZIP 不要解压，同一时间只启用一份插件。

插件本体不需要另装 Python。Apple Silicon 与 Intel Mac 共用源码包。macOS 键盘的 Option 对应 Alt；若系统或自定义键位占用快捷键，可使用面板按钮或在 Blender 键位设置中修改。

## MCP 连接

在下载 wheel 的目录中执行：

```sh
python3 --version
python3 -m venv "$HOME/.venvs/facetcue"
"$HOME/.venvs/facetcue/bin/python" -m pip install ./facetcue-0.5.2-py3-none-any.whl
```

wheel 不包含第三方依赖；首次安装需要 pip 能访问软件源。不要向 Blender 内置 Python 安装这些依赖。

在支持 stdio 的 MCP 客户端配置中填写以下命令，替换为实际绝对路径：

```toml
[mcp_servers.facetcue]
command = '/Users/你的用户名/.venvs/facetcue/bin/python'
args = ['-m', 'agent_mcp.server']
```

保持 Blender 和插件开启。一个实例时自动发现；多个实例时，用面板显示的实例 ID 设置 `ASM_INSTANCE`。Agent 调用 `get_surface_annotations()` 即可读取注释，无需保存场景或选择模型。此 MCP 负责注释读取与完成提交，建模使用其他 Blender 工具。

使用说明及快捷键见 [中文说明](../README.zh-CN.md)。下载包校验可运行 `shasum -a 256 -c SHA256SUMS`。
