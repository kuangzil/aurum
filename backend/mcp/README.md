# Web scraping MCP tool

基于官方 Python MCP SDK `mcp==2.3.0`，提供一个独立的 `scrape_webpage` 工具。
客户端通过标准 MCP 调用服务端；服务端使用 HTTPX 获取网页，用 Beautiful Soup 提取正文。

每个 MCP 工具有自己的目录，所有实现脚本归属该目录。网页抓取对应
[web-scraping Skill](../skills/web-scraping/SKILL.md)，由 Skill 说明调用时机与结果使用方式。

## 安装与快速调用

以下命令从仓库根目录执行，使用 Python 3.11+：

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
# 如果虚拟环境由 uv 创建且没有 pip，也可以使用：
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt

# 客户端自动启动本地 stdio MCP 子进程，调用后自动关闭
backend/.venv/bin/python -m backend.mcp.tools.web_scraping.client https://example.com --max-chars 12000
```

不需要 API key、LLM、数据库或启动 Research/Validation Agent。

## 独立 HTTP 服务

```bash
# 终端 1：默认只监听本机，MCP endpoint 为 http://127.0.0.1:8002/mcp
backend/.venv/bin/python -m backend.mcp.tools.web_scraping.server --transport streamable-http --port 8002

# 终端 2：使用官方 MCP client 连接并调用
backend/.venv/bin/python -m backend.mcp.tools.web_scraping.client https://example.com --server-url http://127.0.0.1:8002/mcp
```

直接运行服务端、不传参数时使用 stdio，等待 MCP host 输入，不会显示交互式命令提示符：

```bash
backend/.venv/bin/python -m backend.mcp.tools.web_scraping.server
```

## 工具接口

工具名称：`scrape_webpage`

```json
{"url": "https://example.com", "max_chars": 12000}
```

- `url`：公开 HTTP/HTTPS 网页，最多 2048 字符，只允许 80/443 端口。
- `max_chars`：返回正文的字符上限，默认 12000，范围 100–50000。

返回标准 MCP `structuredContent`，由 `ScrapedPage` Pydantic 模型定义：

| 字段 | 含义 |
| --- | --- |
| `requested_url` / `final_url` | 输入地址 / 跟随重定向后的来源地址 |
| `title` | HTML 标题，最多 500 字符；纯文本页面为空 |
| `text` | 提取出的正文 |
| `links` | 正文内去重后的链接文字与绝对地址，最多 50 条；不继续抓取 |
| `content_type` / `status_code` | 最终 HTTP 响应类型和状态码 |
| `fetched_at` | UTC 抓取完成时间，不是网页发表时间 |
| `truncated` | 正文是否因 `max_chars` 被截断 |
| `evidence_kind` | 固定为 `external_web_unverified`，不代表已验证的市场证据 |

抓取失败通过 MCP `isError` 返回清晰的工具错误，客户端 CLI 以非零状态退出。
工具有输入/输出 JSON Schema，并标记为只读、非破坏性工具。

## Python 调用

```python
from backend.mcp.tools.web_scraping.client import scrape_webpage

# 在异步函数或未来的 graph 节点中调用：
page = await scrape_webpage("https://example.com")  # 自动启动 stdio 服务
# 或连接已经运行的服务：
page = await scrape_webpage(
    "https://example.com",
    server_url="http://127.0.0.1:8002/mcp",
)
print(page.title, page.text)
```

本次仅实现独立工具，**尚未接入 research graph 或聊天自动调用**。
后续可以在网页研究分支调用该客户端；网页中的文本应始终作为不可信外部内容处理，不能作为系统指令，也不能直接转换为策略验证通过的依据。

## 抓取范围与限制

- 单页静态 HTML、XHTML 或纯文本；不执行 JavaScript，不支持 PDF、登录流程或验证码。
- 优先提取 `main`，其次 `article`，否则提取页面正文；移除脚本、样式、导航、页脚、表单及明确隐藏的元素。复杂页面可能仍包含杂项文本。
- 总超时 20 秒（包含 DNS、重定向和读取），最大响应 2 MiB，最多 3 次重定向。
- 请求不压缩的响应，拒绝忽略该要求的压缩响应，避免在限制前解压过大内容。
- 拒绝 URL 凭据、本机/私有/特殊 IP；每次重定向重新检查全部 DNS 地址。连接固定到已检查的 IP，并保留原始 HTTP Host 和 TLS 验证域名，避免 DNS 二次解析绕过检查。
- 不使用环境代理，不发送调用方凭据，不在重定向间传递 Cookie，也不跨重定向复用 TLS 连接。
- 不自动读取 robots.txt、不做批量爬取；调用方负责选择有权抓取的页面并遵守站点规则。访问拒绝会原样表现为工具错误，不尝试绕过。
- HTTP MCP 服务目前用于本地开发，未增加用户认证。

## 文件结构

```text
backend/mcp/
├── tools/
│   ├── __init__.py
│   └── web_scraping/          # 一个工具一个目录，可包含多个脚本
│       ├── __init__.py       # 工具名称和 Skill 对应关系
│       ├── client.py         # MCP 客户端 + CLI
│       ├── server.py         # MCP 工具注册 + 服务端入口
│       ├── scraper.py        # URL 检查、HTTP 请求、正文提取
│       └── schemas.py        # 此工具的输入输出模型
├── client/web_scraping.py    # 旧入口兼容转发
├── server/web_scraping.py    # 旧入口兼容转发
├── server/scraper.py         # 旧导入兼容转发
└── schemas.py               # 旧模型导入兼容转发

backend/skills/
└── web-scraping/
    └── SKILL.md              # 与 scrape_webpage 对应的 Skill
```

MCP 工具发现结果 `tools/list` 中的 `_meta["aurum/skill"]` 包含 Skill 名称
`web-scraping` 和仓库相对路径 `backend/skills/web-scraping/SKILL.md`。
SDK Python 对象通过 `tool.meta` 读取该元数据。Skill frontmatter 则声明对应
`mcp-tool`、工具包和客户端/服务端模块；这是一对明确的双向引用，尚未实现自动执行调度。

旧命令 `python -m backend.mcp.client.web_scraping ...` 和
`python -m backend.mcp.server.web_scraping ...` 仍可使用；新增代码使用 `tools/` 下的规范路径。

使用 `backend.mcp...` 绝对导入，并始终从仓库根目录执行 `python -m ...`，避免本地目录覆盖官方 SDK 顶层的 `mcp` 包。

## 测试

```bash
backend/.venv/bin/python -m pytest backend/tests/test_web_scraping.py -q
```

测试覆盖 HTML/文本提取、Unicode、截断、重定向、DNS/内网地址防护、响应大小和超时、MCP schema 与工具错误，以及独立子进程的真实 stdio 和 HTTP MCP 调用。网页响应使用确定性测试数据，无需联网；HTTP MCP 集成测试需要本机端口权限。

SDK 参考：[官方 MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)、[客户端](https://py.sdk.modelcontextprotocol.io/client/)、[服务端运行方式](https://py.sdk.modelcontextprotocol.io/run/)。
