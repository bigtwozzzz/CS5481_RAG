# Demo 本地配置、启动与知识库位置

更新日期：2026-11-23。本文对应现有本地 News RAG Demo。界面为英文，本文为中文使用说明。

## 1. 项目在哪里

上传内容都放在 `CS5481_RAG` 仓库内。组员克隆后，按下面的相对路径查找：

```text
CS5481_RAG/
├── demo/frontend/                         React + Vite 前端源代码、package-lock.json
├── scripts/demo/                          本地 API 与 M4 常驻检索进程
├── tests/test_demo_api.py                  Demo API 测试
├── documents/demo/
│   ├── README.md                          英文接口说明
│   ├── Demo_本地配置与启动_中文.md          本文件
│   └── Demo_前端功能与展示指南_中文.md
├── examples/demo/batch_demo_questions.jsonl  17 道演示题
├── configs/m5_budget_cityu_cs5351.json      可复现的调用预算配置
├── .env                                   本地网关设置，不上传
├── .venv/                                 本机 M4 环境，不上传
├── .venv_m5/                              本机 M5／后端环境，不上传
├── .local-m4/                             本地知识库，不上传
└── m5_runs/demo/                          Demo 运行记录，不上传
```

原仓库外的 `project/nocode/` 是旧工作副本。正式维护和上传以仓库内的 `demo/frontend/` 为准，不再要求另外上传 `project/中文`。代码交付不包含数据压缩包或已初始化的知识库；新电脑仍须准备数据和环境。

## 2. 已准备环境时如何启动

打开两个终端，均先进入自己的 `CS5481_RAG` 仓库根目录。以下命令中的环境名对应当前项目约定；环境位置不同可使用后面的覆盖参数。不要把真实密钥写进命令或前端代码。

### 终端一：后端

```bash
.venv_m5/bin/python -B -m scripts.demo.server
```

成功后显示：

```text
RAG API ready at http://127.0.0.1:8765
```

后端默认使用 `.venv/bin/python` 启动 M4 检索。若组员的 M4 环境位置不同，可以指定：

```bash
/path/to/m5/python -B -m scripts.demo.server --m4-python /path/to/m4/python
```

以上 `/path/to/...` 是占位符，不能原样执行。两套环境可以不同，但不要随意替换依赖版本。

### 终端二：前端

```bash
cd demo/frontend
npm ci
npm run dev
```

`npm ci` 按已提交的锁文件安装依赖，首次或依赖变更后执行；后续可以只执行 `npm run dev`。浏览器打开：

[http://127.0.0.1:8080/](http://127.0.0.1:8080/)

Vite 将 `/api` 请求转发到本地 `127.0.0.1:8765`。前后端均仅监听本机，不是公网部署。

需要检查生产构建时，在前端目录执行：

```bash
npm run build
npm run preview
```

`build` 输出到前端的 `build/`。`dev` 与 `preview` 默认都用 8080，不要同时启动。停止终端中的服务可按 Ctrl+C。

## 3. 知识库是什么、在哪里

当前已经准备好的完整目录是：

```text
CS5481_RAG/.local-m4/
├── m3_data/
│   └── data/
│       ├── documents/documents.jsonl
│       ├── chunks/
│       └── vector_store/manifests/
├── runtime_chroma/
│   ├── chroma.sqlite3
│   └── .m4_copy_ready.json
├── model_cache/
│   └── models--sentence-transformers--all-MiniLM-L6-v2/
│       └── snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/
└── m4_workshop_results/           历史结果；不是加载所需的三项核心数据
```

当前知识库有 3,152 篇文档。嵌入模型是 `sentence-transformers/all-MiniLM-L6-v2`，不是生成模型。

准备好的 `m3_data`、运行数据库和模型缓存合计约 1.7 GB（本机检查值）。目前没有单独制作完整 Demo 知识库压缩包。

### 在页面中加载

1. 进入 **Knowledge base**。
2. 点击 **Select local knowledge base**。
3. 浏览到本机 `.local-m4` 目录。
4. 保持选择整个 `.local-m4`，不要进入 `m3_data` 或 `runtime_chroma`。
5. 点击 **Load selected folder**。
6. 等待文档、索引和模型校验，看到 **Knowledge base ready** 后开始使用。

目录窗口的 **Browse** 用于列出输入路径下的子目录；**Parent folder** 返回上一级；**Project workspace** 返回后端项目默认的 `.local-m4`。

加载过程不调用生成模型，不自动下载数据或模型，也不把整个知识库上传到学校网关。实际问答时，会将问题和选中的证据片段发给网关。当前不支持选择任意 PDF、Word 后自动建库。

## 4. 组员第一次使用需要准备什么

仅有代码不够，还需要 Python／Node 环境、M3 数据、M4 运行库、模型缓存及网关配置。

### 数据来源

现有 M3 原始交付包按项目说明从以下页面分发：

[M3 v0.3.0 Release](https://github.com/2718221557-gif/CS5481_RAG/releases/tag/v0.3.0-m3)

- 文件：`CS5481_RAG_stage3_data.tar.gz`，约 536 MB。
- 校验文件：`SHA256SUMS.txt`。
- SHA-256：`89776eabda1e3dd4b1db8f096b970c0fb156357b40017dc8f78c49178f3ff586`。

这是原始 M3 数据包，不等于已经准备好的 `.local-m4`；它不含模型权重或 Python 环境。链接来自项目交付说明，本文不承诺远端附件始终可访问。

详细准备顺序参见：

- [M3 数据交付说明](../m3/DELIVERY.md)
- [M4 初始化说明](../../README_FIRST.md)，重点是 “Start on another machine”
- [M5 中文交接说明](../m5/M5_ABC_HANDOFF_FOR_D_中文.md)

M4 要求 Python 3.11 及项目锁定依赖。使用 `M4_HANDOFF.ipynb` 的初始化单元建立数据库运行副本、校验标记与固定模型缓存；不要手工伪造 `.m4_copy_ready.json`，也不要直接用原始 M3 数据库替代运行副本。不要对正在运行的 Chroma 数据库直接拷贝或打包。

M5／后端环境需安装 `requirements-m5-tokenizer.txt` 中固定的 `tokenizers==0.22.2`；其他校验环境要求以项目交付文档为准。当前 Demo 已验证的是本机现有环境，不是跨平台一键安装器。

## 5. 学校网关与密钥

后端从进程环境读取设置，缺少时再读取项目根目录中被忽略的 `.env`。学校网关需要：

```dotenv
M5_API_BASE=https://YOUR-SCHOOL-GATEWAY/COMPATIBLE-API-BASE
M5_API_KEY=YOUR-OWN-KEY
```

这些只是占位符。使用学校实际提供的兼容 API 基地址，不要重复添加 `/chat/completions`，后端会添加该路径。不要把真实地址中的凭证、密钥或 `.env` 发到 GitHub。

- 生成模型：`CS5351/DeepSeek-V4-Flash`。
- 配置文件：`configs/m5_budget_cityu_cs5351.json`。
- 单次调用应用上限：8192 token；安全余量：512。
- 网络重试：0。
- 8192 是应用策略，不是网关已确认的上下文上限。
- 网关模型分词器一致性尚未验证。
- 没有已核对价格快照，费用显示 **Unknown**，不是 0。

**Backend connected** 仅证明本地 API 可访问，不证明网关鉴权成功；最终以实际请求结果为准。修改环境设置后需在空闲时重启后端，再加载知识库。

## 6. 问题集与运行文件

批量输入是 UTF-8 JSONL，每行只允许 `id` 和 `question`。题号不可重复，最多 100 题，文件不超过 1 MB。

```jsonl
{"id":"demo-001","question":"Which celestial body prompted the 2006 vote on Pluto?"}
{"id":"demo-002","question":"What are the passport numbers of the Australians missing in Nepal?"}
```

仓库已附带 [17 题示例文件](../../examples/demo/batch_demo_questions.jsonl)，位置为 `examples/demo/batch_demo_questions.jsonl`，属于开发与演示题，不是保留集。下载或克隆仓库即可取得这个小文件，不需要额外的数据压缩包。文件选择器受权限限制时，可使用 **Paste JSONL instead**。

Demo 的真实运行记录在 `CS5481_RAG/m5_runs/demo/<任务ID>/`，包含任务快照、各题检索、打包和 pipeline 调用账本。它们与冻结的正式开发集／保留集记录分开，不自动进入正式评分。

## 7. 常见问题

- **Backend offline**：检查后端终端及 8765 端口是否正常。
- **知识库加载失败**：检查完整目录结构、模型版本和运行库标记；不是换一个空目录即可解决。
- **网关未配置或 401/403**：检查后端本地设置及学校权限，不要在前端填密钥。
- **端口被占用**：先关闭重复实例，前端固定端口不会自动换号。
- **刷新后聊天／批量页清空**：当前页面状态不持久化；后端任务文件仍保留，刷新不会自动重发模型请求。
- **材料不足**：这是答案状态，不一定是服务故障；详情见 [功能与展示指南](Demo_前端功能与展示指南_中文.md)。


