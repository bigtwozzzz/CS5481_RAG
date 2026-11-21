# C 审核格式诊断补丁 v0.10.1

2026-11-21 的真实审核记录 `support_13f32d0d506942c39e3e8daf557eac04.json` 返回 ERROR / INVALID_JUDGE_OUTPUT / Invalid overall review fields。记录显示一次 API 调用，输入 2798、输出 380 token。模型已返回可解析的 JSON，但 answer_review 对象的类型或字段集合不符合约定。原代码没有保存被拒对象或字段差异，无法恢复具体差异；不能断言一定是多了相关性字段，也不能判断模型是否正确识别第二句多余。

本补丁保留严格校验、不增加自动重试、不改写原 ERROR，不自动丢弃多余字段或补造缺失值。新增字段级诊断，显示问题所在对象、收到的类型、缺失字段、协议内多余字段和未知字段数量。任意字段名及模型正文不写入这些诊断，避免把输入中的不可信文本当输出。原 JSON 语法错误诊断沿用已有处理。

提示词明确规定 scope_role、relevance_reason 只能位于每条 claim_reviews 中；answer_review 只能包含 recommended_status、status_appropriate、missing_information_accurate、no_unresolved_conflicts、reason 五个字段。提示词版本为 m5-support-en-v0.10.1。公共报告兼容 v0.10 和 v0.10.1 的范围字段要求；旧历史审核仍按原版本读取。

新增八项离线测试，覆盖五个字段逐一缺失、多余字段、错误对象类型、诊断信息边界、不同层级定位、公共 ERROR 报告、命令行展示与保存、无额外修复调用。测试返回全部为模拟，不能当成本次丢失的模型原文，也不能证明真实模型已改正。

本轮先安装、运行离线回归和 --dry-run。真实技术故障复测尚未运行；后续如复测，单独记录为修复技术故障后的一次新调用，保留这次 ERROR，不重复刷到 PASS。C 实际效果验收仍未完成，D 的独立人工评估另行进行。
