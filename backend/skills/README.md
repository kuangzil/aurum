# Research skills

每个 Skill 使用独立文件夹，入口为 `SKILL.md`：描述使用时机、对应 MCP 工具、
参数和结果解释。工具实现与辅助脚本统一放在 `backend/mcp/tools/<tool_package>/`。

| Skill | MCP tool | 实现目录 |
| --- | --- | --- |
| [web-scraping](./web-scraping/SKILL.md) | `scrape_webpage` | [web_scraping](../mcp/tools/web_scraping/) |

对应关系记录在 Skill frontmatter 的 `metadata` 中，同时由工具在 MCP
`tools/list` 的 `_meta["aurum/skill"]` 中公开 Skill 名称和仓库相对路径。
Skill 目录名使用连字符，Python 工具包名使用下划线。

新增工具时，先建立它自己的包目录；即使只有一个脚本也保留此目录边界。
将其对应 Skill 放入独立目录，并维护上述双向引用。不要在 Skill 内复制抓取、
网络连接等实现代码，调用工具客户端即可。

这些是项目内的 Skill 定义；尚未接入 research graph 的 Skill 加载或自动路由，
也不代表已安装到 Codex 的全局 Skill 目录。
