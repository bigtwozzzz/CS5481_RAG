# M5 自动支持性检查使用说明

此增量包在已安装的 M5 接口第一版上增加自动审核功能。它读取已保存的 answer_response.v1，重新核对来源和引文，再使用一次独立的 API 请求判断事实是否有依据、是否切题、回答范围与拒答是否合理。

“独立请求”仅表示不同于生成请求的另一次调用。默认审核模型和生成模型同为 deepseek-flash，可能产生相关错误，不能声称独立可靠，也不能代替人工金标准。程序会明确保留 method=llm_judge、human_review=not_performed、publication_ready=false。

## 安装

在现有项目根目录运行：

```powershell
cd "D:\Cityu SemA\CS5481\CS5481_RAG-main\CS5481_RAG-main"
.\.venv\Scripts\python.exe -X utf8 "C:\Users\13523\Documents\Codex\2026-11-18\new-chat\outputs\M5_support_check_v0_2\INSTALL_SUPPORT.py" --project .
```

新增 support.py、review_cli.py、审核提示词、一份测试文件和本说明。安装器不会替换第一版生成模块，不修改任何已有回答记录，同名不同内容会停止。压缩包必须完整保留，不能只复制安装器。

## 对已经生成的回答执行本地检查

下面使用本次已保存的真实生成记录：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.review_cli --input m5_runs/m5_cae577f8d0d5433f8455da85736480b3.json --dry-run
```

预期 READY_FOR_REVIEW，调用次数0。它验证原文哈希、引用编号、逐字引文及偏移、来源URL映射、展示正文与结构化事实一致性。不调用模型、不要求密钥。

这些检查只证明保存记录内部一致；如果有人同时改了原文和哈希，并重写所有一致字段，它们不能证明记录仍与原知识库相同。原始内容仍需用 chunk_id 回查固定数据集。

## 真正调用模型审核

去掉 --dry-run：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.m5_generation.review_cli --input m5_runs/m5_cae577f8d0d5433f8455da85736480b3.json
```

在终端隐藏输入 DeepSeek 官方 API 密钥。本次最多一次付费调用，不自动重试，不重新生成原答案。默认输出上限2400 tokens。需要换审核模型时可使用 --model；所选模型需支持相同 DeepSeek API 参数。

程序会给每个 claim 及其每个来源分别返回理由，并检查以下事项：

- 主体、数字、单位、时间和“至少”“近似”等限定是否保留。
- 引文是否支持结论，跨片段合并是否误配了事件、主体或时间。
- 是否添加与问题无关的背景事实。
- 状态是否合理，是否遗漏可以回答的子问题，资料缺口是否准确。
- 是否掩盖无法解释的来源冲突。

## 如何解读结果

| 审核状态 | 意思 | 后续行动 |
| --- | --- | --- |
| READY_FOR_REVIEW | 本地结构和完整性检查通过，尚未调用审核模型 | 可以执行真实审核 |
| PASS | 自动审核认为事实、引用贡献、相关性和问题覆盖均可接受 | 人工核对理由；不等于人工通过 |
| FAIL | 自动审核指出至少一个事实、引用或范围问题 | 先检查理由，不要反复调用到通过为止 |
| ERROR | 输入、API或审核模型返回格式出了问题 | 按错误代码排查；不等于事实已判错 |
| NOT_APPLICABLE | 空证据的固定拒答，没有事实供此模块核验 | 不调用模型，也不声称已经证明全库没有答案 |

每个事实的 verdict 可以是 supported、unsupported、contradicted 或 uncertain。每个引用的 verdict 可以是 supports、partial、unrelated 或 contradicts。多个引用分别支持一部分、合起来支持完整事实时允许整体 supported；无关或矛盾的引用不能靠另一个支持来源掩盖。

整体 PASS 由程序根据完整审核列表计算。审核模型必须覆盖本次全部 claim_id/source_id，不能遗漏、重复、增加编号，也不能直接给一个“总分通过”绕过各项检查。没有事实的模型拒答仍要检查问题覆盖和拒答是否合理，此时 support=not_applicable。

原回答不被修改。审核写入新的 m5_runs/support_*.json 文件，其中保存原记录快照、原文件SHA-256、请求编号、审核模型和提示词版本、用量、耗时、每项判定及理由。这个审核结果使用独立 schema m5_support_review.v1，不能冒充新生成的 answer_response.v1。

`publication_ready=false` 是有意保留的。自动审核还未与生成服务串成自动发布流程，也没有实现语义失败后的一次修复。第一版的 --repair-once 仅处理结构与引用定位失败。不要手工将旧答案中的 support 改成 pass 来伪造审查记录。

## 测试和验证边界

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_m5*.py" -v
```

第一版33项，加本版29项，共62项离线测试。模拟的审核输出用于验证控制逻辑、字段完整性、失败处理和日志；它们不证明真实模型可以正确发现35写成3500、错误单位或任何其他语义错误。提示注入测试仅验证资料没有变成系统指令，不证明模型抵抗所有攻击。

已对用户提供的本次真实回答记录执行本地检查，结果 READY_FOR_REVIEW、0次API调用。本次打包过程未使用用户密钥，也没有发出真实审核调用。新审核的真实质量必须通过人工标注的可答、不可答、错误引用、错误数字、错误单位、冲突和时间范围案例评估。

## 尚待完成

1. 人工金标准和自动审核准确性评估，独立记录误放行与误拦截。
2. 审核与生成主流程的门控、语义失败时的最多一次修复及最终输出策略。
3. 真实模型 tokenizer 预算。本版24KB限制仅包含审核提示和序列化内容，不能替代token预算；超限时停止，不删除证据后继续审核。
4. 时间范围约束、真实 M4 联调、课程要求的QA集及报告。
