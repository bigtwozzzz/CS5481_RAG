# M5 接口第一版操作说明

这个版本将前四次练习整理成独立的 `scripts/m5_generation` 模块。输入改成 M4 约定的 JSON 文件，保留 DeepSeek 生成、结构检查、引用定位检查、拒答及错误处理。M4 尚未完成时可以使用随包样例；完成后替换输入文件即可联调。

本版是可联调的初版，不是课程最终完成版。真实模型回答仍须人工核对，不能用本次离线测试数量声称回答正确率。模块不依赖旧的四个 demo 文件，也不依赖其他第三方 Python 包。它已在 Python 3.13.3 下通过离线检查。

## 第一次先做不收费的检查

在 VS Code 的 PowerShell 终端中进入项目根目录，即能直接看到 `scripts`、`data`、`requirements.txt` 的目录。

```powershell
cd "D:\Cityu SemA\CS5481\CS5481_RAG-main\CS5481_RAG-main"
```

安装命令使用完整安装包里的 `INSTALL_M5.py`。它会添加模块、样例、测试和说明文件，不复制虚拟环境或旧练习；遇到同名不同内容的文件会在开始复制前停止。相同内容允许重复运行。

```powershell
.\.venv\Scripts\python.exe -X utf8 "C:\Users\13523\Documents\Codex\2026-11-18\new-chat\outputs\M5_interface_starter_v0_1\INSTALL_M5.py" --project .
```

只验证输入和证据包：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_ok.json --dry-run
```

预期显示 `状态：READY_FOR_GENERATION`、`证据数量：2`、S1/S2 映射，以及 `本次 API 调用次数：0`。结果写入 `m5_runs` 中的新文件，终端会显示完整路径。

这里 `--dry-run` 表示不调用模型、不输入密钥、不消耗 API 额度。READY_FOR_GENERATION 是内部预览状态；该结果使用 `m5_evidence_preview.v1`，不是最终答案。

## 无证据和故障必须分开

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_no_evidence.json --dry-run
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_error.json --dry-run
```

第一条应显示 `INSUFFICIENT_SOURCES`；第二条应显示 `ERROR` 并保留上游 `INDEX_NOT_FOUND`。两次 API 调用均为 0。ERROR 命令返回退出码 1 是预期行为，不代表测试失败。

所有样例都标记为 fixture，使用项目现有 chunks_B 的前两个片段，但没有执行真实检索。检索分数全部为 null，检索耗时 0 是明确标注的占位值，不可放入实验结果。样例没有可用于证明 M4 质量的命中率。

## 跑离线测试

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p test_m5_generation.py -v
```

目前有 33 个测试方法，涵盖多组输入变化。所有 API 响应均模拟，不读密钥，不联网调用模型。测试中的提示注入案例只证明资料没有被提升为系统提示，不能证明模型能抵御所有提示注入。

## 接入 DeepSeek

确认上述步骤成功后，可以去掉 `--dry-run`：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_ok.json
```

程序在交互终端中隐藏输入密钥，发送问题和证据给 DeepSeek 官方接口。每次正常运行默认最多一次调用，会使用账号额度。它不读取聊天里的密钥，不写密钥到日志，也不自动读取其他环境变量里的凭据。

默认模型 `deepseek-flash`、非思考模式、temperature=0.1、最大输出1600 tokens。模型名称可用 `--model` 指定。官方模型别名可能更新，日志保留请求模型及 API 返回的模型字段；这不等价于固定底层权重版本。

部分回答和证据中无答案可分别使用以下输入：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_partial.json
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_unanswerable.json
```

预期分别为 PARTIAL 和 INSUFFICIENT_SOURCES，但真实模型输出仍需复核。不得反复运行直到得到想要的状态，再只报告成功的一次。

## 一次修复

增加 `--repair-once` 时，首次输出在 JSON、字段或引用检查上失败，程序可以基于相同证据重新生成一次，并在提示中说明失败代码。不会搜索新资料，也不会把被拒绝的模型文本当成新指令。最多两次 API 调用，两次用量都记录。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.cli --input examples/m5/retrieval_ok.json --repair-once
```

认证、余额、限流、网络和超时错误直接报告 ERROR，不自动重试；这仍是有界的处理策略。两次输出均不合格时返回 ERROR，不将技术性校验失败包装成“知识库没有答案”。当前修复不涵盖语义支持错误，因为本版尚无自动语义判定器。

## 输出如何判断

| 字段 | 含义 |
| --- | --- |
| status | ANSWERED、PARTIAL、INSUFFICIENT_SOURCES 或 ERROR；生成结果的状态尚须人工核对 |
| request_id | 原样沿用 M4 请求编号；无法读取有效编号时为 null |
| review_required | true 表示仍需人工核对，不是正式发布许可 |
| publication_ready | 模型生成的答案和拒答均为 false；只有根据 M4 空结果生成的固定拒答可为 true |
| validation.support | 有事实时为 unchecked；没有事实时为 not_applicable |
| validation.answerability | 模型判断的可回答范围为 unchecked；输入明确无证据时为 no_retrieval_evidence |
| claims | 通过结构和引用定位检查的事实，每条仍需检查含义 |
| sources | 只展示实际使用的来源，标题、URL、日期来自 M4 |
| evidence | 本次实际发送的完整证据包，供重放和人工核对 |
| excluded_evidence | 因输入体积限制排除的片段编号及理由 |
| validation_log | 每次生成输出的检查结果和失败代码 |
| generation.calls | 每次 API 请求的耗时、返回模型、token 用量和接口错误代码 |

API 没有返回用量时记录 null，不能按0计算。`cost_usd=null` 表示没有计算费用，不表示免费。相同 request_id 可有多次运行记录，输出文件使用新的本地编号，避免覆盖。`--output` 可指定文件；已存在时拒绝覆盖。

引用通过只证明原文可定位。错数字、错单位、跨文档结论、来源冲突和问题覆盖需要另行核验。不能只判断 `status == "ANSWERED"` 就展示为已验证答案。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| scripts/m5_generation/contracts.py | 输入字段、状态、排名、哈希、分数、日期和 URL 基本一致性检查 |
| scripts/m5_generation/context.py | S 标签和完整证据包、超量时移除低排名片段 |
| scripts/m5_generation/api.py | DeepSeek 请求、隐藏密钥输入、有限超时、响应解析 |
| scripts/m5_generation/validator.py | 生成字段、来源白名单、逐字引文和偏移检查 |
| scripts/m5_generation/generator.py | 连接输入检查、生成、可选一次修复和输出记录 |
| scripts/m5_generation/cli.py | 文件输入和命令行运行入口 |
| scripts/m5_generation/prompts/generation_v1.txt | 版本化提示词，明确只回答问题所需事实 |
| examples/m5/ | 五份固定输入样例 |
| tests/test_m5_generation.py | 可重复运行的离线测试 |

## 后续必须完成的工作

1. 与 M4 对齐实际输出格式，并在真实检索结果上联调。当前来源 URL 的语法与域名检查不能证明它属于正确文章，正确 metadata 仍须回查数据或数据库。
2. 支持性、可回答范围和来源冲突评估。人工标注为准；如果增加独立模型检查，要记录为自动判定，并评估其错误。不得将 unchecked 改成 pass 来绕过工作。
3. 本版只用提示要求历史资料不能冒充实时信息，还需在正式链路落实语料截止日期和用户时间要求检查。
4. 使用所选模型真实 tokenizer 预算。当前16KB是系统提示和用户正文的 UTF-8 字节上限，不是token预算；它不包含协议包装开销。低排名完整片段可被移除，但不剪断原文。模型输出上限为1600 tokens。
5. 冻结模型和提示配置，建立独立开发/测试集，报告事实正确性、引用支持率、误拒、耗时和实际费用。当前自动检查及三个单篇新闻示例不足以完成课程验收。

本包未修改远程仓库，没有为用户运行付费 API。新模块完成了离线迁移验证；旧练习成功的真实 API 结果不能冒充新模块的在线联调结果。
