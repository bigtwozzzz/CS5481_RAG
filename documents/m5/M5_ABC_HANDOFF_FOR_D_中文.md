# CS5481 M5 总交接说明

交付日期：2026年11月21日
交付范围：A 检索适配与证据构建、B 生成与编排、C 契约与支持性验证
主要接收人：负责 QA 建设、M5 效果评估与 M6 评估报告的 D 同学
目标仓库：https://github.com/bigtwozzzz/CS5481_RAG

## 1 先读这一页

A、B、C 的上游工程实现、功能检查和交接材料已经完成。D 可以开始接入评估，无需等待我们另写一套生成流程。**工程已完成不等于答案质量已验收**：新开发集、独立保留集、人工评分、G0/G1/G2 对照及 M6 最终报告仍待开展。

D 最需要使用的内容如下。本文中的项目相对路径均以克隆后的仓库根目录为起点；历史 JSON 内的 D 盘、C 盘绝对路径只用于溯源，不能直接当作 D 电脑上的运行路径。

| D 要做什么 | 使用什么 | 需要注意什么 |
|---|---|---|
| 运行问题到答案的批量流程 | `python -m scripts.m5_generation.b_cli` | 当前推荐入口；默认不调用付费 API，显式 `--generate` 才调用 |
| 获取原始检索候选和打包证据 | A 的 `results.jsonl`、`item_XXXX/retrieval.json`、`packing.json` | 原始候选、M4 选中证据、最终 M5 证据应分开统计 |
| 获取逐题最终结果 | B 的 `predictions.jsonl` | 用 `id` 关联题集；行内没有问题原文，也没有金标准 |
| 查看生成、修复和审核全过程 | 每题 `pipeline.json` 与 `contracts/` | 以预测行提供的相对路径和哈希定位；不要猜文件名 |
| 统计调用、token 和费用 | `pipeline.api_calls`、批次 `run.json` | 物理请求只计一次；缺失用量或费用保留未知，不能记零 |
| 人工核验自动审核 | `validation_report.v1`、逐条 `claim_reviews` | supported、相关性、完整性分开；自动 PASS 不是人工金标准 |
| 了解当前局限 | 本文第 10 至 12 节 | 已用演示题不算新保留集；多数语义边界测试使用模拟 verdict |

建议顺序：读本文 → 安装并验证环境 → 运行两道已有题的无付费预检查 → 检查 D 的题集输入 → 核对费用设置后小批量真实运行 → 开发集评估 → 冻结 → 保留集 → 人工复核及报告。旧 `documents/m5/README.md`、`SUPPORT_CHECK_zh.md` 等保留了早期状态；当前使用方法以本文和 B v0.9、C v0.10.1 为准。`README_FIRST.md` 仍是 M4 的交接说明，其中“未实现 M5”描述的是当时 M4 交付范围。

## 2 已完成的内容与证据

| 分工 | 已交付能力 | 已有验证证据 |
|---|---|---|
| A | 单问与 JSONL 适配；去重；完整片段选择；S 标签与偏移；新旧打包策略；输入与过滤拒绝 | 两道已用题 × k=3/5/10，共 6 组真实检索、12 次策略检查、12 次 M5 预算检查通过；API 0 次 |
| B | 检索到生成、引用校验、模型审核、最多一次共享修复；批量结果；调用与费用记录 | 真实两题批次得到 ANSWERED 和 INSUFFICIENT_SOURCES；4 次物理请求，契约通过 |
| C | 四份公共 Schema；引用定位与事实支持分开；相关性理由；保守处理 uncertain；技术错误记录 | 261 项离线测试通过；真实 Eris 案例识别 C2 有依据但多余，最终 FAIL；三份新旧审核可导出公共报告 |

当前工程版本组合为 A v0.8、B v0.9、C v0.10.1。最终上传后的 Git commit 尚未产生，不能在报告中编造；合并后请记录真实 commit SHA。不同模块的内部版本号不要求相同，运行记录中的代码和提示词哈希才用于精确追溯。

已有真实 PARTIAL、INSUFFICIENT_SOURCES、ANSWERED 以及技术 ERROR 记录用于功能说明；它们来自不同历史版本，不能合并成“当前冻结版本的正式评测结果”。上传包另附分类索引，明确真实记录、人工构造输入和模拟案例。

## 3 环境和数据准备

当前验证环境为 Windows PowerShell，保留两个独立 Python 环境：

| 环境 | 本机验证版本 | 用途 |
|---|---|---|
| `.venv_m4` | Python 3.11.9；Chroma 1.5.9；sentence-transformers 5.7.0；tokenizers 0.23.3 | 检索、嵌入模型与数据库 |
| `.venv` | Python 3.13.3；tokenizers 0.22.2；jsonschema 4.26.0；numpy 2.5.5 | 生成、预算、审核、公共契约及离线回归 |

B 当前在 Windows 路径下调用 `.venv_m4/Scripts/python.exe`。另一平台的干净安装尚未验收；不要直接称为跨平台可复现。不要把 `.venv_m4` 的 tokenizers 版本装到 M5 环境，M5 预算模块会检查 0.22.2。

在新电脑的仓库根目录创建环境并安装依赖；已有可用环境不必重复创建：

```powershell
py -3.11 -m venv .venv_m4
.\.venv_m4\Scripts\python.exe -m pip install -r requirements-m4.txt
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-m5-tokenizer.txt -r requirements-m5-contracts.txt "numpy==2.5.5"
```

以上 Python 命令要求相应解释器已安装。版本为本机已验证记录；若目标电脑无对应安装包，应记录并处理环境差异，不静默换版本后仍称为完全相同环境。本机曾遇到 pip 卡在 Windows WMI 查询，已解决；不要仅因安装慢就删除环境。

M3 数据和嵌入模型不随 Git 上传。先读 `README_FIRST.md`，再运行 `M4_HANDOFF.ipynb` 的初始化和集成检查。M3 数据来源为 README 内的 Release 链接，归档 SHA256 为：

```text
89776eabda1e3dd4b1db8f096b970c0fb156357b40017dc8f78c49178f3ff586
```

B 的实时入口需要工作目录包含下列布局：

```text
M4_work/
  m3_data/data/documents/documents.jsonl
  m3_data/data/chunks/
  m3_data/data/vector_store/manifests/
  runtime_chroma/chroma.sqlite3
  runtime_chroma/.m4_copy_ready.json
  model_cache/models--sentence-transformers--all-MiniLM-L6-v2/
    snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/
```

按 Notebook 建立运行数据库副本和标记，不要手工伪造标记。原始 M3 数据库不能作为运行目录；B 不会自动下载模型或复制缺失数据库。D 可把工作目录放在自己的盘符，命令中的 `--work-base` 指向该目录。原交付者使用 `D:\Cityu SemA\CS5481\M4_work`。

模型为 all-MiniLM-L6-v2，上述 revision 已固定，维度 384、L2 归一化、cosine 距离。M5 的离线 tokenizer 位于 `vendor/m5/deepseek_v4_tokenizer/`，属于代码交付所需小型资源，不能连同大模型缓存一起误删。

## 4 D 的输入题集约定

传给 A/B 的 JSONL 每行只允许 `id`、`question` 和可选 `filters`；推荐先仅用前两项。问题使用英文，id 在文件内唯一。当前适配器拒绝非空过滤，日期过滤返回 `UNSUPPORTED_DATE_FILTER`，不会静默忽略。

```jsonl
{"id":"dev_001","question":"What discovery sparked the IAU's 2006 vote on Pluto?"}
{"id":"dev_002","question":"What are the passport numbers of the Australians missing in Nepal?"}
```

这两题只演示格式，已经用于开发，不能加入新的独立保留集。现成同类文件为 `examples/m5/a_smoke_questions.jsonl`。

D 应独立保存完整标注，例如 `reference_answer`、`required_facts`、原文证据、不可答原因、event_id 和数据集划分。**这些金标准字段不得出现在传给 A/B 的 JSONL 中**，否则入口会拒绝。评估器通过 id 把输出与金标准关联；不要以数组位置代替 id。非法行仍应作为输入错误记录，重复 id、空问题和未知字段不能被悄悄删除。

输入文件限制 5 MB、最多 1000 行有效请求。B 默认最多 10 题，正式 15 或 25 题批次必须显式提高 `--max-items`。所有运行目录必须是新目录，无自动恢复；不能用原目录覆盖重跑。

## 5 最小运行流程

在仓库根目录运行。下列无付费步骤不需要 API key。

第一步，运行离线回归：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_m5*.py"
```

本交付版本预期为 261 项通过。测试中的模型回答多为模拟，用于验证程序逻辑，不代表真实语义准确率。

第二步，仅检查 JSONL 和配置，不启动检索：

```powershell
.\.venv_m4\Scripts\python.exe -B -X utf8 -m scripts.m4_retrieval.cli --input-jsonl examples/m5/a_smoke_questions.jsonl --packing-policy skip_continue_dedup_v1 --check-only
```

第三步，真实本地检索加 M5 预算预检查，仍不调用 DeepSeek：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.b_cli --input-jsonl examples/m5/a_smoke_questions.jsonl --work-base "D:\Cityu SemA\CS5481\M4_work" --packing-policy skip_continue_dedup_v1 --top-k 5 --network-retries 0 --dry-run
```

将 `--work-base` 换成 D 的路径。正常逐题显示 `READY_FOR_PIPELINE; contracts: PASS`。这只说明准备好进入生成，不是回答成功。运行会打印一个新批次目录，其中包含 `retrieval/` 与 `generation/`。

第四步，检查预运行文件后，以同一批已保存证据进行真实生成，避免再检索一次。先在同一个 PowerShell 中加载密钥：

```powershell
. .\scripts\m5_generation\SET_KEY_FOR_SESSION.ps1
```

这是交接附带的隐藏输入小脚本，密钥只进入该终端会话环境变量，不显示、不存盘。关闭终端后需重新设置。不要将实际密钥写进代码、JSONL、命令参数、GitHub 或截图。

随后运行以下模板，`实际批次目录` 必须替换为第三步生成的目录：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.b_cli --retrieval-run "m5_runs\实际批次目录\retrieval" --max-items 10 --network-retries 0 --generate
```

此命令会消耗额度。每题正常生成加审核约 2 次逻辑请求，最多 4 次；这里关闭网络重试，因此物理请求也最多 4 次/题。没有提供有效 `--pricing-json` 时费用显示未知，但保留服务端 usage；这不表示免费。

做正式评估时，D 应核对当时实际模型价格，按 `configs/m5_pricing.template.json` 创建独立快照，再加 `--pricing-json "配置路径"`。模板的 null 值故意不能用于计费。旧验收的周末价格只属于历史记录，不可作为永久价格。预算上限不是费用上限。

对于新题集，把第三步输入替换为 D 的仅问题 JSONL，并提高 `--max-items`。一条命令也可同时实时检索并生成：第三步将 `--dry-run` 换为 `--generate`；正式对照建议先保存检索，复用同一份证据。

## 6 配置和对照实验边界

| 参数 | 当前演示设置 | D 如何控制 |
|---|---|---|
| strategy | C | 用独立 `--config` 文件选择 A/B/C |
| mode | hybrid | 同配置可选择 dense、bm25、hybrid |
| top_k | 5 | B 显式 `--top-k 3/5/10`；命令行会覆盖配置文件中的值 |
| candidate_k | 30 | 配置文件，保持对照条件一致 |
| rrf_constant | 60 | 配置文件 |
| context_tokens | 1024 | M4 嵌入 tokenizer 的上下文预算，不等于 DeepSeek 输入预算 |
| packing_policy | B 默认 skip_continue_dedup_v1 | B 显式 `--packing-policy` 会覆盖配置；A 配置默认仍是 legacy_break_v1 |
| network_retries | B 默认 1 | 本文示例显式设为 0，避免不知情地增加物理请求 |

配置文件是 JSON 语法的 YAML 子集；保持 JSON 语法，不依赖额外 YAML 解析器。请复制配置为新的实验文件，不覆盖历史配置。

旧策略遇到放不下的块就停止；新策略继续尝试后续可完整放下的块，并对同来源同元数据同文本去重。它不截断片段；重复 chunk_id 属于非法输入。不同来源或有冲突的元数据不能被去重合并。比较两策略时复用同一批原始候选，记录策略版本，不能先改变检索结果再归因于打包。

M5 输入预算为系统提示和用户内容的离线计数，加生成输出预留 1600、审核预留 2400（对应不同调用）、安全余量 512，在应用设定的 8192 总上限内检查。8192 是应用限额，不是对服务商当前最大上下文的声明。服务端 tokenizer 完全一致性未验证；API usage 是用量依据。真实 C 复核曾出现本地 2940、服务端 2964 的差值，已如实记录。

现有主流程对应 G2，即结构化生成、硬校验、自动支持性检查及最多一次修复。**没有已经验收的 G0/G1/G2 一键对照参数**。D 需要另行组织 G0、G1 的评估驱动，并与 B/C 确认接口；不能把 G2 结果删掉审核字段后冒充 G1。`--dry-run` 不是 G0/G1，`--no-repair` 也不等于取消审核。对照应固定问题、模型和证据，保留未引用事实，并使用同一人工评分口径。

## 7 输出目录和字段读取

实时 B 运行的典型结构：

```text
m5_runs/b_<id>/
  questions.jsonl
  retrieval_config.json
  retrieval/
    run.json
    results.jsonl
    item_0001/retrieval.json
    item_0001/packing.json
  generation/
    run.json
    predictions.jsonl
    item_0001/retrieval.json
    item_0001/pipeline.json
    item_0001/contracts/
```

如果使用 `--retrieval-run`，新 B 输出目录直接包含 `run.json`、`predictions.jsonl`、`item_XXXX/`，不再额外套一层 `generation/`。读取日志打印的路径，不硬编码两种布局。

| D 的读取目标 | 文件与字段 | 统计或关联规则 |
|---|---|---|
| 逐题身份 | predictions 的 `id`、`line`、`request_id` | id 关联 D 题集；line 为物理输入行；request_id 用于内部溯源 |
| 最终状态与正文 | `status`、`gate`、`answer`、`claims`、`sources`、`missing_information` | 同时检查 `local_contract_checks`、`error`；不能只看正文是否为空 |
| 原始候选 | A retrieval 文件中 `retrieval.results` | 预算前检索指标；使用 rank、chunk_id、document_id 和原文 |
| M4 打包 | 同文件 `selected_chunk_ids`、`context_tokens`，以及 packing 审计 | 预算后 M4 覆盖；packing 报告包含标签、选择和偏移信息 |
| 最终模型证据 | 被接受的 `answer_record.evidence` 或该次 attempt 的 evidence_bundle | 才是生成实际可引用的证据；不能用所有候选替代 |
| 引用定位 | claims 的 `source_ids`、`evidence_quotes`、`located_quotes` | 偏移是 Python Unicode 字符索引，左闭右开，不是 UTF-8 字节偏移 |
| 自动审核 | attempts 内 review 或公共 validation_report | 逐条事实 verdict、citation_reviews、relevant、scope_role、relevance_reason |
| 修复情况 | `pipeline.repair_used`、`attempts` | attempts 包含被拒绝的原草稿；失败内容不能算最终答案 |
| 请求与用量 | `pipeline.api_calls` | 每条为一次物理请求；含 stage、logical_call、network_attempt、状态与用量 |
| 费用 | B run 的 `billing`、`pricing_snapshot` | total_cost 未知时保持 null；known_response_cost 仅为已知小计 |
| 耗时 | A elapsed_seconds、检索 timing_ms、B/pipeline timing_ms | 区分初始化、单次检索、生成审核、批次总耗时；不得把批次耗时当每题耗时 |
| 版本绑定 | run 的 `code_sha256`、输入哈希、pipeline_sha256 | 再补充 Git commit、数据集哈希及模型/索引版本进入实验清单 |

`predictions.jsonl` 的 `pipeline_file` 相对于其所在 B 输出目录；读取后核对 `pipeline_sha256`。公共契约验证失败时预测行可能被压成 ERROR，而原 pipeline 仍保留诊断和费用；不要跳过错误行去捞原草稿当最终答案。

请求总数以批次 `api_requests` 或物理请求 ledger 统计一次。不要把 generation.calls、judge.calls 和 api_calls 相加，否则重复计数。失败、超时、取消可能已经产生费用；未知用量不是零。

## 8 四种状态和错误规则

| 状态 | 含义 | D 的评分处理 |
|---|---|---|
| ANSWERED | 当前流程认为已回答且通过所需检查 | 仍需人工检查是否正确、完整、引用充分 |
| PARTIAL | 回答了一部分并明确资料缺口 | 单列部分回答；不得直接记全对或完全拒答 |
| INSUFFICIENT_SOURCES | 当前提供的证据不足以回答 | 用 D 的独立标签判断是否正确拒答；不能据此反向造金标准 |
| ERROR | 检索、预算、API、解析、契约或最终审核失败 | 技术或流程错误，不计为正确拒答，不从分母静默剔除 |

READY_FOR_RETRIEVAL、READY_FOR_PIPELINE 是预检查内部状态，不是最终回答状态。M4 `OK` 只表示检索到候选。无候选可以触发固定拒答；有候选但没有完整块能放入预算为 `EMPTY_SELECTED_CONTEXT`，属于预算/系统错误。

自动审核 FAIL 与技术 ERROR 区分：FAIL 表示模型给出了有效审核但内容不通过；格式不合法为 `INVALID_JUDGE_OUTPUT`，解析失败为 `INVALID_JSON`。G2 在语义失败时最多一次共享修复，最终仍失败为 `ERROR / BLOCKED / REVIEW_REJECTED`。uncertain 不能自动提升 PASS。独立 review_cli 只复核，不自动改写答案。

所有当前生产流程输出均为 `publication_ready=false`。自动审核与人工批准分开；D 的人工评分应保存在单独文件中，不改写原 JSON 中的 judge verdict 或旧记录。

## 9 C 的公共契约和真实回归案例

四份契约为 `schemas/evidence_bundle.v1.schema.json`、`generation_draft.v1.schema.json`、`validation_report.v1.schema.json`、`answer_response.v1.schema.json`。标签、URL、引用逐字定位、可见片段、偏移、正文及 claims 一致性先做本地硬校验。

Python 接口：

```python
from scripts.m5_generation.public_contracts import (
    validate_answer, validation_report_from_review
)
from scripts.m5_generation.support import check_support
```

`validate_answer(answer)` 通过仍不代表语义支持已验证；`check_support(answer, dry_run=True)` 仅检查输入和预算，正式调用为付费自动审核。`validation_report_from_review(answer, review)` 会核对对象哈希、输入快照和请求身份，防止把其他答案的审核结果套用过来。

当前提示词版本 `m5-support-en-v0.10.1`，实际文件为 `scripts/m5_generation/prompts/support_v1.txt`。每条审核把事实 `reason` 与 `relevance_reason` 分开，scope_role 为 direct_answer、essential_qualification 或 unnecessary。历史旧格式可读取，新调用必须提供新字段。

真实 Eris 回归案例问“哪项发现引发 IAU 投票”：C1 回答发现 Eris，C2 补充 Eris 在柯伊伯带。两句都有原文支持，但 C2 不属于问题所需。旧 judge 误判相关而 PASS；v0.10 遇到字段格式错误而 ERROR；v0.10.1 把 C2 判为 unnecessary/relevant=false，最终 FAIL，符合该案例预期。三份记录原样保留。**这一例证明程序在该例中区分了支持性与必要性，不证明审核器的总体准确率。**

期望范围来自用户明确偏好及助手分析，并非独立人工金标准。D 需要单独人工评分。数字 35 改为 350 的历史案例使用人为构造错误草稿和真实旧版模型调用，可用于回归说明，不能当作新版本独立效果评测。

## 10 D 需要继续完成的内容

1. **新题集与标注。** 按事件隔离开发集和保留集。分工建议开发集 15 题、保留集 25 题，其中保留集 20 道可答和 5 道不可答；可根据时间调整，但报告实际数量。标注必要事实、证据和不可答原因，不可答须检查语料和相关原文，不能由一次检索失败决定。
2. **检索指标。** 计算 Hit@k、证据 Recall@k、Complete@k、MRR、文档级命中，并分开预算前候选与预算后证据覆盖。新开发集控制 k=3/5/10、预算及其他变量；A 配合检索配置与问题修复。
3. **人工答案与引用评分。** 检查完整性、事实正确性、必要事实、引用支持及覆盖；单列 PARTIAL、正确拒答、误拒和 ERROR。自动 judge 不能充当人工标签，争议题由另一人复核。
4. **G0/G1/G2 对照。** 先与 B/C 对齐评估驱动，固定同一问题和证据，控制提示词、模型及预算差异。G0 未引用事实也计入事实覆盖分母；未经硬校验的 G0 仅作离线评估。
5. **运行清单和冻结。** 保存代码 commit、数据集哈希、索引 manifest、模型 revision、提示词、预算、重试策略、价目及运行时间。配置冻结后才运行保留集；看过保留集后调参不能继续宣称同一轮独立测试。
6. **统计和报告。** 给出逐题记录、人工评分表、汇总指标、分子和分母、错误分析及 p50/p95 耗时与费用；技术错误保留在全请求口径，可另报成功请求口径。整理 M6 报告和演示。

建议产物路径为 `scripts/m6_evaluation/`、`configs/m6/`、`data/evaluation/`、`results/m6/<run_id>/` 和 `documents/m6/`。这些是分工建议，不表示本交接已实现了 M6 模块。评分表可包含 id、event_id、split、run_id、status、事实完整性、正确性、引用支持、覆盖、拒答是否合理、reviewer、争议与复核结论。

## 11 数据使用边界与已知局限

- 原 M4 的 27 条 QA 和 9 组实验输出保留。24 道测试题已参与配置选择，3 道开发题来自同一洪水事件，不能重新称为未见过的独立保留集。
- `examples/m5_contracts/`、模拟价格和八个边界案例是接口或流程测试数据，不能混入正式质量或真实费用统计。文件中的 provenance/fixture 标记应保留。
- 261 项离线测试验证结构、绑定、状态机和故障处理。错误数字、主体、限定词、复合事实和冲突等语义案例中，多数 verdict 为模拟，不等于真实模型识别率 100%。
- 提示注入测试检查证据位于不可信数据区，不等于完整攻防评测。没有完成独立人工质量评分或大样本可靠性验证。
- 生成与审核使用同一模型体系，分两次调用不代表独立可靠裁判。deepseek-flash 是模型别名，记录返回模型也不等于固定了服务端底层权重。
- 预算使用官方离线样例；与服务端完全一致尚未证明。费用是估算，不是账号账单；错误调用费用可能未知。
- 批次无自动恢复。中断后先检查保存的请求 ledger，记录已发请求和未知结果，不能直接重跑并删除失败记录。版本变更后应重新建立评估配置。

## 12 D 接收时的核对清单

- 确认 GitHub PR 已合并或明确使用哪个分支，记录 commit；本文件制作时尚未上传。
- 确认四份 Schema、A/B/C 代码、三份提示词、tokenizer 资源和测试均已收到。
- 确认 M3 数据、数据库副本和固定嵌入模型可用；这些通过 Release 或小组存储交付，不在代码包内。
- 离线测试和两题无付费预检查通过后，再运行经核对额度的小批次生成。
- 检查 D 题目 JSONL 不含金标准；新题集与历史回归题明确分开。
- 读取 predictions 与 pipeline，验证 id、路径、哈希、错误和调用用量能正确关联。
- 与 A/B/C 确认 G0/G1 驱动及人工评分口径，然后开始新开发集实验。

A/B/C 上游完成清单无遗留项；D 的新题集评估、人工核验、消融、报告尚未完成。后续发现检索、编排或审核问题时，分别交给 A、B、C 修复。全组共同分担人工评分与演示，不把所有收尾工作集中给 D。
