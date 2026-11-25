# Issue tracker: GitHub

本仓库的 Issue 和 Spec 发布到 `SunGuistar/Personal-Assistant` 的 GitHub Issues。使用 `gh` 操作。首次创建 Issue 前，从当前工作区运行 `gh repo view --json nameWithOwner` 核对目标仓库。

## Conventions

- **创建 Issue**：`gh issue create --title "<title>" --body-file "<file>"`。多行正文通过文件传入。
- **读取 Issue**：`gh issue view <number> --json number,title,body,labels,comments`。
- **列出 Issue**：`gh issue list --state open --json number,title,body,labels,comments`，按需使用 `--label` 和 `--state` 过滤。
- **关联父子 Issue**：用 `gh issue create --parent <parent>` 或 `gh issue edit <parent> --add-sub-issue <child>`（`gh` 2.94+）。旧版 `gh` 可调用 `POST repos/<owner>/<repo>/issues/<parent>/sub_issues`，以 `sub_issue_id` 传入子 Issue 的数据库 ID。仓库不支持子 Issue 时，在子 Issue 正文顶部写 `Part of #<parent>`。
- **阻塞依赖**：使用 GitHub 原生 Issue 依赖。用 `gh issue create --blocked-by <number>` 或 `gh issue edit <child> --add-blocked-by <blocker>`（`gh` 2.94+）。旧版 `gh` 可调用 `POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by`，以 `issue_id` 传入阻塞 Issue 的数据库 ID。仓库不支持依赖时，在正文顶部写 `Blocked by: #<number>`。
- **检查阻塞**：`gh api repos/<owner>/<repo>/issues/<n> --jq .issue_dependencies_summary.blocked_by`。若使用 `gh issue view <number> --json blockedBy`，只统计仍处于打开状态的阻塞 Issue。
- **添加评论**：`gh issue comment <number> --body-file "<file>"`。
- **添加或移除标签**：`gh issue edit <number> --add-label "<label>"` 或 `--remove-label "<label>"`。
- **关闭 Issue**：先添加说明评论，再运行 `gh issue close <number>`。

Issue 和 PR 共用编号。无法确定编号类型时，先用 `gh pr view <number>` 查询，再按需使用 `gh issue view <number>`。

## Pull requests as a triage surface

**PRs as a request surface: no.**

若日后启用，PR 与 Issue 使用同一套标签和状态。使用 `gh pr view`、`gh pr diff`、`gh pr comment`、`gh pr edit` 和 `gh pr close` 操作。列出外部 PR 时，排除作者关系为 `OWNER`、`MEMBER` 或 `COLLABORATOR` 的条目。

## When a skill says "publish to the issue tracker"

在已核对的目标仓库创建 GitHub Issue。若正在运行的 Skill 指定标签，按该 Skill 的要求应用。

## When a skill says "fetch the relevant ticket"

按上文的「读取 Issue」约定读取正文、标签及评论。

## Wayfinding operations

- **Map**：创建一个带 `wayfinder:map` 标签的 Issue，记录 Notes、Decisions-so-far 和 Fog。
- **Child ticket**：将子任务关联到 Map，并使用 `wayfinder:<type>` 标签，类型为 `research`、`prototype`、`grilling` 或 `task`。无法使用原生子 Issue 时，在 Map 中使用任务列表，并在子 Issue 正文顶部写 `Part of #<map>`。
- **Blocking**：沿用上文的 Issue 依赖约定。
- **Frontier query**：按 Map 顺序找出仍打开、未分配且没有未关闭阻塞项的子任务。
- **Claim**：`gh issue edit <number> --add-assignee @me`。
- **Resolve**：在子 Issue 评论中记录结论，关闭该 Issue，再向 Map 的 Decisions-so-far 补充摘要和链接。
