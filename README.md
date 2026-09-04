<div align="center">

# Paper-Agent++

面向科研人员的智能论文检索、阅读、分析与综述写作工作台。

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Frontend-Vue%203-42B883?logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![LangGraph](https://img.shields.io/badge/Workflow-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![uv](https://img.shields.io/badge/Package%20Manager-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)

</div>

## 项目简介

Paper-Agent++ 是一个本地运行的 AI 论文调研工具。用户可以从研究主题或具体论文题目开始，完成论文检索、相关性判断、全文阅读、研究分析和综述写作，并在浏览器工作台中查看每个阶段的进度与产物。

项目采用 FastAPI + Vue 3 + LangGraph 架构。后端负责检索、Agent 工作流和本地数据保存，前端负责会话工作台、论文结果列表、个人论文库、系统设置和账户管理。

## 主要功能

### 论文检索

- 支持两种检索模式：
  - **搜论文**：适合输入一个具体论文标题，优先进行标题匹配和精确筛选。
  - **搜主题关键词**：适合输入研究方向，自动拆分子主题并生成检索条件。
- 支持多来源检索：
  - arXiv
  - OpenAlex
  - Semantic Scholar
  - IEEE Xplore
  - Elsevier / Scopus
- 多来源结果统一格式化、去重、评分和排序。
- 支持编辑检索关键词、来源、年份范围、结果数量和排除词。
- Google Scholar 当前显示在界面中但默认禁用，项目没有使用不稳定的网页抓取方式。

### 论文结果与个人论文库

- 结果列表显示标题、作者、年份、来源、相关度和摘要。
- 支持关键词筛选、排序、分页和打开原文链接。
- 可以单独下载论文原文，不执行总结或综述生成。
- 支持标记重点阅读、忽略、收藏、标签和笔记。
- 个人论文库按账户保存，可在后续调研中复用。
- 支持上传本地 PDF，并与在线检索结果一起分析。
- 支持指定论文重新分析。

### 调研工作流

- 摘要阅读和相关性判断。
- 全文下载、PDF 解析、Markdown 转换、文本分块和结构化抽取。
- 子主题分析和全局综合分析。
- 自动生成综述大纲、证据映射和分节正文。
- 支持暂停后继续、失败后重试和从上次阅读现场恢复。
- 显示检索数量、全文成功数量、失败数量和各阶段运行状态。
- 使用 SSE 推送实时进度，浏览器刷新后仍可恢复历史会话。

### 导出与账户

- 导出 Markdown、Word、PDF。
- 导出 BibTeX、GB/T 7714 和 APA 引用格式。
- 注册、登录、退出和本地账户隔离。
- 修改密码、找回密码、删除账户。
- 查看登录设备并退出其他设备。
- 会话支持自动标题、手动重命名、归档和恢复。

## 工作流

```mermaid
flowchart LR
    A[研究主题或论文题目] --> B{检索模式}
    B -->|搜论文| C[标题匹配与精确检索]
    B -->|搜主题关键词| D[拆分子主题与生成检索式]
    C --> E[多来源检索]
    D --> E
    E --> F[去重与相关度评分]
    F --> G[摘要阅读]
    G --> H[全文下载与解析]
    H --> I[子主题分析]
    I --> J[全局综合]
    J --> K[大纲与证据映射]
    K --> L[综述写作与导出]
```

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.12+、FastAPI、Uvicorn |
| 工作流 | LangGraph |
| 前端 | Vue 3、TypeScript、Vite、Vue Router |
| 模型调用 | SiliconFlow、OpenAI 兼容协议、Anthropic 协议 |
| 论文来源 | arXiv、OpenAlex、Semantic Scholar、IEEE Xplore、Elsevier / Scopus |
| 全文处理 | pypdf、Markdown、文本分块 |
| 数据保存 | SQLite、本地 JSON、Markdown、文件系统 |
| 向量库 | ChromaDB |

## 环境要求

- Windows 10 或 Windows 11
- Python 3.12 或更高版本
- Node.js 18 或更高版本
- `uv`
- npm
- 可用的大模型 API Key

## 本地开发

### 1. 安装依赖

在项目根目录打开 PowerShell：

```powershell
uv venv --python 3.12
uv sync
npm run front:install
```

如果本机已经存在可用的 Python 3.12 环境，可以直接执行：

```powershell
uv sync
npm run front:install
```

### 2. 配置模型

复制示例配置：

```powershell
Copy-Item config/model.example.json config/model.json
```

然后编辑 `config/model.json`，填写模型服务配置。也可以启动后在网页的“系统设置”页面中配置和测试 Provider。

最少需要配置：

- `providers` 中的模型服务地址和 API Key。
- `agents.default_agent`。
- `embedding_profiles.default_embedding`。

推荐使用环境变量保存密钥，例如：

```powershell
$env:SILICONFLOW_API_KEY="你的 API Key"
```

`config/system.yaml` 用于配置阅读数量、论文缓存目录、下载超时、IEEE Xplore 和 Elsevier 等论文来源密钥。

### 3. 启动项目

推荐使用统一入口：

```powershell
npm run start
```

该命令会先构建 Vue 前端，然后启动 FastAPI。启动后打开：

```text
http://127.0.0.1:8000
```

只需要一个终端窗口，FastAPI 会同时托管 API 和前端页面。

### 4. 其他启动方式

前端已经构建完成时，可以只启动后端：

```powershell
uv run python main.py
```

开发后端默认开启热重载。API 文档地址：

```text
http://127.0.0.1:8000/docs
```

如果只修改前端界面，可以单独启动 Vite：

```powershell
npm run front:dev
```

此时访问：

```text
http://127.0.0.1:5173
```

## 论文来源配置

arXiv 和 OpenAlex 可以在没有额外 API Key 的情况下使用，但不同来源可能有访问频率限制。

IEEE Xplore 和 Elsevier / Scopus 需要官方 API Key。可以在网页“系统设置”页面填写，也可以配置环境变量：

```powershell
$env:IEEE_XPLORE_API_KEY="你的 IEEE Xplore API Key"
$env:ELSEVIER_API_KEY="你的 Elsevier API Key"
```

也可以写入 `config/system.yaml`：

```yaml
paper_retrieval:
  openalex_api_key: null
  semantic_scholar_api_key: null
  ieee_xplore_api_key: null
  elsevier_api_key: null
```

## Windows exe

项目提供目录版 Windows 打包脚本。目录版比单文件 exe 更适合本项目，因为程序运行时需要写入数据库、日志、论文缓存、会话产物和模型配置。

### 生成 exe

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_exe.ps1
```

生成目录：

```text
release\Paper-Agent++\
├── Paper-Agent++.exe
├── config\
├── front\dist\
├── assets\
├── data\
├── logs\
└── 运行说明.txt
```

### 启动 exe

双击：

```text
release\Paper-Agent++\Paper-Agent++.exe
```

程序会自动打开浏览器并使用：

```text
http://127.0.0.1:8000
```

关闭 exe 对应的黑色窗口，服务会一起停止。

注意：打包脚本会复制当前本地的 `config/model.json`。这个文件可能包含个人 API Key，发布到 GitHub 或发送给别人前，必须删除密钥，不能直接上传整个 `release` 目录。

## 项目结构

```text
Paper-Agent++/
├── main.py                         # 开发环境启动入口
├── packaging/                      # Windows exe 入口、spec 和打包脚本
├── config/
│   ├── model.json                  # 本地模型配置，不应提交
│   ├── model.example.json          # 模型配置示例
│   └── system.yaml                 # 系统默认参数
├── front/                          # Vue 3 + TypeScript 前端
├── src/
│   ├── agents/                     # Search、Read、Analyse、Writing Agents
│   ├── api/                        # FastAPI 应用和接口路由
│   ├── graph/                      # LangGraph 工作流和节点
│   ├── llm/                        # Provider、模型配置和调用适配
│   ├── models/                     # 会话、论文和协议模型
│   ├── paper_retrieval/            # 论文来源连接器和检索服务
│   ├── repositories/               # SQLite、JSON、文件和向量库持久化
│   ├── services/                   # 会话、运行、设置、账户和论文库服务
│   └── utils/                      # 日志、缓存、PDF 解析和文本分块
├── data/                           # 本地数据库、会话和论文缓存
├── logs/                           # 本地日志
└── test/                           # unittest 测试和联调辅助代码
```

## 数据与隐私

- `config/model.json` 可能包含模型 API Key，不要提交到 GitHub。
- `data/` 可能包含账户、会话、论文笔记、论文全文和导出文件，不要提交到 GitHub。
- `logs/` 可能记录请求路径和运行信息，不要提交到 GitHub。
- `release/` 是本地打包输出，不建议提交到 GitHub。
- 使用第三方模型和论文来源时，请遵守对应服务的 API 使用条款和论文版权规定。

## 验证

运行后端测试：

```powershell
uv run python -m unittest discover -s test -v
```

构建前端：

```powershell
npm run front:build
```

当前项目已验证后端单元测试、前端构建和 exe 启动流程。

## 贡献

欢迎提交 Issue 和 Pull Request。提交前建议完成：

1. 说明问题的复现步骤或功能目标。
2. 运行后端测试和前端构建。
3. 不提交 API Key、数据库、日志、缓存和本地打包文件。
4. 在 PR 中说明配置文件、数据库结构或用户界面的影响。

## 原项目与致谢

本项目基于原始项目 [Tswoen/Paper-Agent](https://github.com/Tswoen/Paper-Agent) 继续开发。

特别感谢原项目贡献者 [@GreatZack](https://github.com/GreatZack) 的持续投入与核心贡献。

## License

本项目采用 [MIT License](LICENSE)。
