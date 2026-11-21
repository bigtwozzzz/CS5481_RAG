# M5 代码上传 GitHub 操作说明

目标仓库：https://github.com/bigtwozzzz/CS5481_RAG
当前情况：本地项目来自解压，没有 `.git`；你尚无目标仓库写入权限。
推荐方式：Fork → 克隆个人副本 → 创建分支 → 导入 M5 交付文件 → 提交 → 推送 → Pull Request。

此流程保留你原来已运行成功的 D 盘项目。不在旧目录执行 `git init`，不强制推送、不覆盖小组主分支。这里的上传包只包含本次 M5 新增文件及选定交接证据，不包含环境、数据库、缓存、备份或全部运行历史。

## 1 在 GitHub 建立自己的副本

登录自己的 GitHub 账号，打开目标仓库，点击右上角 **Fork**。Owner 选择你的账号，仓库名保留 `CS5481_RAG`，点击 **Create fork**。

成功后地址应为 `https://github.com/你的用户名/CS5481_RAG`。这就是你有权限推送的副本。若仓库因私有或组织设置不允许 Fork，则请仓库负责人邀请你为 collaborator；邀请未接受前不能推送到原仓库。不要向聊天提供 GitHub 密码、访问令牌或 DeepSeek 密钥。

## 2 克隆到新的目录

在 PowerShell 执行以下命令。把 URL 中的“你的用户名”替换为你的实际账号；其余路径可保持。

```powershell
Set-Location -LiteralPath 'D:\Cityu SemA\CS5481'
git clone https://github.com/你的用户名/CS5481_RAG.git CS5481_RAG_M5_upload
Set-Location -LiteralPath 'D:\Cityu SemA\CS5481\CS5481_RAG_M5_upload'
git remote add upstream https://github.com/bigtwozzzz/CS5481_RAG.git
git fetch upstream
git remote show upstream
```

如果 `CS5481_RAG_M5_upload` 已存在，不覆盖或删除它，先检查其中是否有自己的工作。`git remote show upstream` 的 **HEAD branch** 表示小组默认分支。若显示 `main`，执行：

```powershell
git switch -c codex/m5-abc-handoff upstream/main
```

若显示 `master`，把上面的 `upstream/main` 改为 `upstream/master`。如果分支名其他，使用真实名称。这样基于小组最新代码建分支，不依赖个人 Fork 是否已同步。

## 3 先检查再导入 M5 文件

交付包已生成在本机以下位置；从别处下载时先解压，然后使用实际解压路径。

```text
C:\Users\13523\Documents\Codex\2026-11-18\new-chat\outputs\M5_GITHUB_DELIVERY_20261121
```

在新克隆目录运行检查。使用旧项目已安装好的 Python 执行工具，无需在上传目录重新安装依赖：

```powershell
& 'D:\Cityu SemA\CS5481\CS5481_RAG-main\CS5481_RAG-main\.venv\Scripts\python.exe' -B -X utf8 'C:\Users\13523\Documents\Codex\2026-11-18\new-chat\outputs\M5_GITHUB_DELIVERY_20261121\APPLY_TO_CLONE.py' --repo . --check-only
```

工具会检查克隆目录是干净的 `codex/` 分支、必要 M4 文件是否与已验证版本一致、已有文件是否冲突、交付包哈希是否正确。出现 `CONFLICT` 或 `STOP` 时先保留输出，不要用强制复制绕过。如果 GitHub 已有更新，需按实际差异合并。

仅在检查通过后导入：

```powershell
& 'D:\Cityu SemA\CS5481\CS5481_RAG-main\CS5481_RAG-main\.venv\Scripts\python.exe' -B -X utf8 'C:\Users\13523\Documents\Codex\2026-11-18\new-chat\outputs\M5_GITHUB_DELIVERY_20261121\APPLY_TO_CLONE.py' --repo . --apply
git status --short
git diff -- .gitignore
```

导入工具只新增已审查文件并在 `.gitignore` 末尾追加本地环境/运行记录排除项，不执行 commit 或 push。新增文件中包括给 D 的总交接说明和 `M5_README_FIRST.md`，原 M4 README 保留。

## 4 检查并暂存

如果文件清单与预期一致，再执行明确目录的暂存，不使用 `git add .`：

```powershell
git add -- .gitignore .gitattributes M5_README_FIRST.md requirements-m5-tokenizer.txt requirements-m5-contracts.txt scripts/m4_retrieval/cli.py scripts/m4_retrieval/packing.py scripts/m5_generation scripts/m5_live schemas configs tests examples documents/m5 vendor/m5
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
```

应看到 M5 代码、Schema、提示词、测试、配置、说明、固定 tokenizer 资源和少量分类历史证据。**不应出现 `.venv`、`.venv_m4`、整个 `m5_runs`、更新备份、模型权重、Chroma 数据库或密钥文件。** `documents/m5/handoff_evidence/` 是特意选取并分类的回归记录，不能与被排除的全部运行目录混淆。

`tokenizer.json` 约 6.4 MB，是离线预算所需文件；它不是大型嵌入模型权重。已保留来源与哈希，不新增未经核实的授权声明。`.gitattributes` 保留 M5 文件的原始字节，避免 Windows 换行转换破坏固定资源和历史记录的哈希；应一起提交。上传包已做常见密钥模式扫描，但仍应查看暂存文件清单。

如果有意外文件，先停止提交并检查。Git 提交不需要 DeepSeek 密钥。若 Git 尚未配置作者身份，按提示在当前仓库设置自己的姓名及 GitHub noreply 邮箱，不必全局修改：

```powershell
git config user.name "你的GitHub用户名"
git config user.email "你在GitHub设置中看到的noreply邮箱"
```

## 5 提交并推送到个人 Fork

```powershell
git commit -m "Add M5 retrieval adapter generation pipeline and validation handoff"
git push -u origin codex/m5-abc-handoff
```

如提示登录 GitHub，按 Git 的浏览器认证流程操作。不要把密码或令牌发到聊天，也不要把令牌嵌入仓库 URL。若遇到 403，先核对 `origin` 是否指向自己的 Fork，而不是没有写入权限的 `bigtwozzzz` 仓库。

## 6 发起 Pull Request

在自己的 Fork 页面点击 **Compare & pull request**。检查：base repository 为 `bigtwozzzz/CS5481_RAG`；base branch 为实际默认分支；head repository 为你的 Fork；compare branch 为 `codex/m5-abc-handoff`。

标题建议：`Add M5 A B C pipeline and evaluation handoff`。

描述可以直接复制：

```text
This change adds the M5 retrieval adapter, evidence packing, bounded generation/review pipeline, public schemas and batch records. D can use scripts.m5_generation.b_cli for evaluation integration; the Chinese consolidated handoff is documents/m5/M5_ABC_HANDOFF_FOR_D_中文.md.

Validation: 261 offline M5 tests passed on the delivered local Windows environment. Real functional runs cover answer generation and insufficient-evidence handling. The current C review correctly rejects a supported but unnecessary sentence in the Eris regression case. Historical incorrect acceptance and technical review failure are preserved.

Scope: engineering and functional delivery only. Independent development/holdout evaluation, human scoring, G0/G1/G2 comparisons and the M6 report are not complete. The package excludes virtual environments, databases, model caches, secrets and full run history. Tokenizer assets retain provenance and hashes. No current clean installation on another machine is claimed.
```

先让组员审查并合并；不要自行强制覆盖主分支。上传到 Fork 或 PR 已创建不等于已合并。合并后记录真实 commit SHA，并让 D 使用确定的版本。

## 7 当前进度

A、B、C 工程交付均完成；D 总交接文件与上传包已准备。GitHub 上传、PR、合并和 D 的独立质量评估尚未完成。本说明是操作指导，不代表已替你创建 Fork、提交代码或发送消息。
