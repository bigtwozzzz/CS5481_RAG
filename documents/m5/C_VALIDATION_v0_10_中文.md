# C：输出契约、引用与支持性验证

本材料对应《M56并行的四项分工》中的人员 C。A、B 工程交付已完成；C 本次增强审核的相关性记录，交付安装包和离线检查。新提示词的真实模型复核尚未完成，不等待 D 的新题集。

## 本次问题与修改

B 的真实付费运行中，问题只问哪项发现引发 IAU 投票。第一句回答 Eris，第二句补充 Eris 的位置。第二句有原文支持，但用户已明确不需要该背景。旧模型把它同时标为 supported、relevant=true，相关性理由实际只证明了原文支持。

v0.10 保留 `reason` 作为事实支持理由，新增 `scope_role` 和 `relevance_reason`，分别记录该句是直接回答、必要限定还是多余内容，以及为什么对问题有必要。程序要求这两个字段完整，并校验 `scope_role=unnecessary` 必须对应 `relevant=false`。相关性不通过进入 B 已有的一次内容修复；修复仍失败则阻止答案展示。审核 JSON 无效属于 ERROR，不当作知识拒答。

这些约束让审核更可追溯，但不能从结构上证明理由正确。模型仍可能给出错误理由；不得把字段完整、模拟测试通过或自动 PASS 写成已完成人工质量验收。

## 接口与版本

- 本地硬校验：`scripts.m5_generation.public_contracts.validate_answer(answer)`。成功只说明结构、引用定位、来源映射和输出一致性通过，语义支持仍是 unchecked。
- 自动支持性接口：`scripts.m5_generation.support.check_support(answer, dry_run=False, ...)`，返回保存格式 `m5_support_review.v1`。它复用 `review_answer`；`dry_run=True` 只检查输入与预算，不调用 API。
- 报告适配：`validation_report_from_review(answer, review)` 检查答案对象哈希和输入快照，防止把其他答案的审核挪用到当前答案。
- 四份公共 Schema 保持原文件名；本次对 `validation_report.v1` 兼容性扩展两个字段，`judge.prompt_version=m5-support-en-v0.10` 时必须有新字段。接收方需同步更新 Schema 文件。其他三个 Schema 不变。
- 历史 v0.7.2 审核可以按旧格式读取，其历史 PASS 原样保留；这不代表它通过了 v0.10。新的模型调用不接受旧格式。版本标记和对象哈希用于追溯，不是密码学签名。
- 提示词实际位置为 `scripts/m5_generation/prompts/support_v1.txt`；文档中的 judge_v1 是分工建议名，不再另外维护重复提示词。
- 程序与提示词输出英文；本交接说明中文。

## 错误和判定

| 结果/错误码 | 含义 | 后续处理 |
|---|---|---|
| CITATION_VALIDATION_FAILED | 标签未知或引文无法逐字定位 | 不展示草稿；按已有修复上限处理 |
| INVALID_SAVED_ANSWER | 来源、偏移或显示正文与记录不一致 | 本地拒绝，不调用模型 |
| INVALID_JUDGE_OUTPUT | 审核字段缺失、类型错误或范围标记自相矛盾 | 技术 ERROR，不自动当作拒答 |
| INVALID_JSON / API_TIMEOUT 等 | 审核解析或通信故障 | 保留技术错误；独立审核不自动重试 |
| REVIEW_BINDING_ERROR | 审核与答案对象不匹配 | 阻止导出为已审核答案 |
| FAIL | 审核认为事实、引用贡献、相关性或范围不通过 | 向 B 返回结构化原因，最多一次共享内容修复 |
| uncertain | 无法确定语义支持 | FAIL，不能自动升级 PASS |
| PASS | 自动模型审核通过 | 仍不是人工批准；publication_ready=false |

没有结果的检索与 ERROR 区分仍沿用 A/B。无证据拒答不冒称进行了语义审核。状态约束与四种状态示例沿用已交付公共契约和 B 交接包。

## 离线检查与人工对照

新增 `tests/test_m5_validation.py`。包含真实 Eris 原回答的模拟相关性拒绝、旧格式兼容、新格式必填字段、伪造标签与引文、URL 与偏移变更、数字/主体/限定词/复合事实错误、冲突标记、不确定判定、文档指令隔离、审核解析故障、修复上限及预算预检查。

硬校验案例检查实际本地拒绝；语义案例使用明确标注的模拟 verdict，检查程序是否正确处理。模拟语义错误被拦截不等于真实模型识别率达到 100%。文档指令检查只验证指令放在不可信数据区，不宣称完成真实提示注入攻防评测。

`examples/m5/c_validation/real_eris_answer.json` 与 `real_eris_original_review.json` 是真实历史记录的副本；`provenance.json` 记录来源和期望范围。原模型结论不改写。期望 C2 为 unnecessary 来自用户既定范围要求与助手分析，不是独立人工金标准，也不计入 D 的新开发集或保留集。

## 当前交接和剩余步骤

交给 A：引用可见范围、唯一标签和来源绑定要求。交给 B：`check_support`、结构化错误与相关性修复原因。交给 D：四份 Schema、新旧报告兼容说明、真实失败案例及模拟测试；D 在新题集上组织独立人工评分，测量审核实际可靠性。

本轮尚待用户本机安装及回归，随后对原 Eris 草稿进行预先限定的一次真实审核，保留结果，不反复调用直到通过。若仍误判，记录真实失败并继续分析；不以删除原句后再审核替代原失败案例。真实审核无论 PASS 或 FAIL 都不自动完成人工批准。

本包不包含新质量评测、D 的题集、账号账单或真实提示注入测试。A/B 已完成的工程交付不依赖这些后续评估。
