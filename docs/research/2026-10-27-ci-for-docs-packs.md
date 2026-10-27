# 数据包的 CI：让「打 OpenHarmony 文档包 → 发 release」由 GitHub Actions 完成（2026-10-27）

**结论先行**：选 **A**。oh-docs-corpus 自己持有一个调用方 workflow（`.github/workflows/pack.yml`），
照家族硬规则和 CONTRACT 里适用的条款写，不往 ci-workflows 加复用 workflow。决定性的事实是
GitHub 不允许公开仓调用私有仓里的复用 workflow，而 ci-workflows 是私有仓（§1）。打包脚本的正本搬进本仓
`tools/build-docs-corpus.py`，这样仍然零 secret（§2）。发布的触发方式是推一个 tag，tag 名必须**逐字等于**
release 名 `openharmony-zh-cn-<YYYYMMDD>-<commit8>`。`guard` 先解析 gitcode commit，再核对这个名字，
做法与 CONTRACT §6「tag 逐字是 `v<version>`」一样。`workflow_dispatch` 只空跑。不设定时任务（§3）。
发布前依次过：离线自检、页数下限（≥ 5000，且 ≥ 上一包的 90%）、逐篇 git blob sha1 复核、清单与资产名核对、
`.sha256` 旁挂、「必须比 latest 新」。发布顺序是先建 draft、再上传、最后转正（§4–§5）。

- **起因**：主会话任务书（2026-10-27）——第一份包 `openharmony-zh-cn-20261027-aad3246e` 是维护者手跑脚本、手工发布的；
  oh-cli ADR-0109 把这个公开仓定成 `oh docs update --corpus openharmony` 的主路。
- **范围**：本仓的 CI 形态、脚本归属、触发、校验、幂等、权限。**消费契约不动**：manifest 的字段
  `{corpus, lang, source, commit, committed_at, documents, bytes, sha256, license, asset}`、
  资产名规则、zip 布局，以 oh `src/docs_corpus/update.rs::check_release_manifest` 为准。
- **实测环境**：oh-vm（aarch64 openEuler，经代理），2026-10-27。**GitHub runner 上一次都没跑过**，
  只有真跑一次 workflow 才能证明的事项列在 §8。

## 1. A 还是 B

| | (A) 本仓自己的调用方 workflow | (B) ci-workflows 新建复用的 `data-pack-release.yml` |
|---|---|---|
| **能不能被本仓调用** | 能 | **不能**。GitHub 文档 *Reusing workflow configurations*（2026-10-27 读）写明：公开仓只能调用公开仓里的复用 workflow；私有仓里的复用 workflow 只对 Access 设置放行的**私有**仓可用。ci-workflows 是私有仓，ONBOARDING §1 也把「私有仓」列为整套流水线的前提。这一条只读了文档，没实际试 |
| 「One fix, every caller」 | 只有一个调用方，没有「N 份漂移的拷贝」可言 | 只有一个消费方时，这条原则拿不到任何回报 |
| 「a tool's own build logic stays in the caller」 | 打包逻辑（gitcode 取数、sha1、zip 布局）本来就是本仓的事，放在这里正合这条规则 | 复用 workflow 只能做到「跑调用方给的命令，再发调用方给的文件」，真正的逻辑还是留在调用方。中心仓多出来的只是一层接口，还要担 `v1` 移动的爆炸半径 |
| 代价 | 家族规则在这里会多出一份遵守副本（不是实现副本），见附录 A 的「公开调用方」缺口 | 要把 ci-workflows 转成公开仓，或者另开一个公开的复用仓；这两件都会改变家族的安全前提（CREDENTIALS、私有仓假设） |

**推荐 A。** 就算 ci-workflows 是公开仓，只有一个消费方时 B 也不值得做。等出现**第二个**数据包调用方时再议，
到那时也应该先确认它是私有仓还是公开仓，因为这一点决定 B 在物理上能不能实现。

A 并不等于脱离家族规范。`pack.yml` 的头注逐条点名所遵守的硬规则：5（ubuntu-22.04）、7（无 secret、无 `set -x`）、
8（不写读端先退出的管道）、9（顶层 `contents: read`，只有 `publish` job 有 `contents: write`）、
10（`retention-days: 1`）、4（`.sha256` 格式）。actions 的钉法照 ci-workflows 现有 workflow：
`actions/checkout@v5`、`upload-artifact@v6`、`download-artifact@v7`，按主版本钉。
发布用 runner 自带的 `gh`，没用 ci-workflows 用的 `softprops/action-gh-release@v3`。原因有三：
少一个持 `contents: write` token 的第三方 action；`--verify-tag` 和 `--latest` 是一等参数；draft→转正的两步走能显式写出来。

## 2. 打包脚本的归属

**推荐：正本搬进本仓 `tools/build-docs-corpus.py`；oh-cli 删掉 `scripts/build-docs-corpus.py`，改成指向这里。**

| | 利 | 弊 / 风险 |
|---|---|---|
| 正本在本仓 | workflow 检出自己就有脚本，**零 secret**（不需要 `SIBLING_TOKEN`，硬规则 2 的场景根本不会出现）。release notes 记着 workflow 的 `GITHUB_SHA`，「谁打了这个包」可以追到一个公开 commit。公开仓里的脚本人人可审，语料是 CC BY 4.0 再分发，可审本身是好事 | **NOTICE 文本、资产名规则、zip 布局是跨仓契约**：oh 的 gitcode 后备路要产出同一种形状（`oh_notice` 与本脚本的 `notice()` 逐字节相同）。正本搬走以后，这个耦合从「同仓两份」变成「跨仓两份」 |
| 留在 oh-cli（私有）| 与 `oh_notice` 同仓，改一处时容易顺手改另一处 | CI 要读私有仓就得配 `SIBLING_TOKEN`（违背零 secret）；或者手工同步一份拷贝（必然漂移） |

**怎么压住跨仓漂移**：两边各自钉住同一份字节。oh 侧有 `src/docs_corpus/update/tests.rs` 里的 NOTICE 字面量断言；
本仓的 `--self-test` 新增 `NOTICE_GOLDEN_SHA256`，它是固定 commit/日期下 `notice()` 输出的 sha256，
已与 oh 测试里的字面量逐字核对过（oh-vm，2026-10-27）。改文本时两边都会变红，必须两仓同批改。
manifest 字段集合由 `MANIFEST_KEYS` 钉住，资产名由 self-test 的断言钉住。

**脚本的运行行为不变**：manifest 字段、资产名、zip 布局、取数步骤都没动。新增的都是可选参数：
`--resolve`、`--verify DIR`、`--min-documents`、`--previous-manifest`、`--pages-tsv`、`--expect-asset`、`--require-newer`。
`--commit` 现在也接受 7–40 位前缀。

**顺带修了一个既有缺陷**：原脚本的 `--commit <sha>` 解析走 `GET commits/<sha>`，而 gitcode 这个单条接口的应答
**不带 `commit.tree`**（oh-vm 实测，2026-10-27，`aad3246e` 全长和 8 位前缀都一样）。所以指定 commit 的构建
必然在 `gitcode commit answer has no usable sha / tree` 处停下。第一份包是 master 路径打的，没撞上这个缺陷。
现在改走列表接口 `commits?sha=<ref>&per_page=1`，它接受分支、全长 sha 和前缀，并且带 tree（实测），
另外加了一条检查：应答的 sha 必须以所请求的前缀开头。oh 自己的后备路只用 `sha=master`，不受影响。

## 3. 触发模型

家族的两条约束是：不跑 push CI（ONBOARDING §1）；`workflow_dispatch` 一律只空跑（CONTRACT §6，设计原则 5）。

| 方案 | 怎么发 | 与家族规则 | 评估 |
|---|---|---|---|
| ① `workflow_dispatch` 加 `publish: true` 输入 | 维护者点一下 | **违背** §6「dispatch 从不发布」 | 否。一个布尔输入就能发版，正是 §6 要防的事 |
| ② 推 `pack-*` tag，由 workflow 生成 release 名 | `git push origin pack-xxx` | 合 tag 发布的惯例，但 tag 名和 release 名是两回事 | 可行。但每次发布会留下两个 tag（触发 tag 和 release tag），而且推之前不知道会发出什么 |
| ③ **推的 tag 逐字就是 release 名** `openharmony-zh-cn-<YYYYMMDD>-<commit8>` | 先 `--resolve` 拿到名字，再 `git tag -a <名> && git push origin <名>` | **直接对应** §6：`guard` 用 tag 里的 `<commit8>` 向 gitcode 解析出全长 sha 和日期，重新算出名字，必须与 tag 逐字相等，否则在构建之前就停下 | **推荐**。发布什么，tag 上写得清清楚楚；tag 指向的本仓 commit 同时钉住了打包脚本的版本；与第一份手工 release 的 tag 同一命名空间 |
| ④ 定时任务 | 无人值守 | 家族惯例默认关（研究 2026-10-04 §3：定时任务曾占 9 月分钟的 11%） | **不开**，理由见下 |

**分钟成本。** 一次发布 = 一条约 9 分钟（oh-vm 读数；runner 上未测）的 ubuntu 腿，加一条约 1 分钟的 `publish` 腿。
已经发过的 commit 在 `guard` 里就跳过，不发 gitcode 请求，也不构建。另外，**本仓是公开仓**：GitHub 计费文档
（*GitHub Actions billing*，2026-10-27 读）写的是「公开仓使用标准 GitHub-hosted runner 免费」，
所以这些分钟理应**不计入** Pro 的 3000 分钟额度（CONTRACT §6.1）。这一点只读了文档，账单上没核实；
第一次真跑后用 `fed bill ci --by repo` 看本仓是不是 0。也就是说，CONTRACT §6.1 的分钟带在本仓不是约束，
真正的约束是 gitcode。

**gitcode 限流风险。** 每次发布约 6,100 次匿名请求（130 页列目录 + 5,964 篇 + LICENSE），没有书面配额
（oh-cli 研究 2026-10-27 §2 / U3：约 6,500 次请求没遇到 429，但约有 0.5% 的瞬时失败需要重试）。
脚本对每篇最多试 3 次，任何一篇最终失败，整包放弃，什么都不写。GitHub runner 在境外，
到 gitcode 的延迟和是否被区别对待**都没测**（§8）。

**为什么不开定时任务**：分钟在公开仓免费，所以理由不在钱。理由有三。第一，无人值守的 6,100 次请求，
等于在没有书面配额的接口上加一个固定负载，一旦被限流，没人在场判断。第二，无人看过就把新包推成
`releases/latest`，会直接改变每个用户 `oh docs update` 的结果。第三，GitHub 会在公开仓 60 天没有活动后
自动停用定时 workflow（GitHub 文档；未在本仓验证），定时任务会悄无声息地停下。如果维护者以后要按月自动出包，
再加 `schedule:` 也只是一行改动。`guard` 的幂等跳过已经保证「master 没动就不构建」，而定时触发不是 tag 事件，
所以那一行还要配一条「定时等同发布」的规则，这需要另做一次裁定。

## 4. 发布前校验

全部在 `build` job 里按顺序跑，任何一步红都不发布；`publish` job 拿到 artifact 后再复核一遍。

| # | 检查 | 在哪 | 防的是 |
|---|---|---|---|
| V1 | `--self-test`（离线，合成 gitcode，含 NOTICE 金样、篡改页、下限、校验器的每条红路） | build 第 1 步 | 脚本本身坏了 |
| V2 | 名字：tag 必须逐字等于 `--resolve` 算出的名字 | guard | 发出的东西与 tag 不符 |
| V3 | **必须比 latest 新**：`committed_at` 晚于 latest manifest 的，且 commit 不同 | guard（构建前）、verify、publish 复核 | `releases/latest` 指的是最近**创建**的 release，发一个旧 commit 会让所有用户退回旧文档 |
| V4 | **页数下限** = max(5000, ⌈0.9 × latest.documents⌉)，列目录之后、拉取之前就检查 | build（`--min-documents` + `--previous-manifest`），verify 再查一次 | gitcode 回了残缺的列表（今天 5,964 → 下限 5,368） |
| V5 | 逐篇 git blob sha1：拉取时比对 tree 里的 sha；**解压后再按 `--pages-tsv` 逐篇复算** | build + verify | 拉取被篡改、zip 写坏 |
| V6 | manifest 字段集合**恰好**是那 10 个，固定值字段、`asset` 等于名字规则、`bytes` 和 `sha256` 与文件一致、`documents` 等于 zip 里的页数 | verify | 消费契约漂移 |
| V7 | zip：CRC（`testzip`）、`LICENSE`/`NOTICE` 排在最前、只含 `docs/**.md`、路径安全、有序、无重复、deflate 且无 data descriptor；NOTICE 逐字节等于该 commit 的署名；LICENSE 是 CC BY 4.0 | verify | oh 的读取器拒收，或署名不对 |
| V8 | oh 消费侧的上限（zip ≤ 256 MiB、条目 ≤ 64,000、单篇 ≤ 4 MiB、解压总量 ≤ 512 MiB，取自 oh `001439b7`） | verify | 包能发出去，却在每个用户机器上失败 |
| V9 | `<asset>.sha256`：`sha256sum` 写、`sha256sum -c` 验，格式为 `<hash>` + 两个空格 + `<file>` + LF（CONTRACT §1、硬规则 4）；verify 逐字节核对格式 | build、publish | 旁挂格式不对 |
| V10 | 发布后用 oh 的同一个 URL 读回 `releases/latest/download/manifest.json`，与刚发的逐字节相同 | publish 最后一步（**只报警**，发布已经公开，无法撤回） | 缓存或 latest 标记没生效 |

**多出一个 `<asset>.sha256` 资产，会不会破坏 oh？** 不会。oh 只取 `manifest.json`，再取 manifest 里 `asset` 指定的那个文件
（`from_release`，oh `update.rs`），不枚举 release 资产。旁挂是给人用和给 `sha256sum -c` 用的，属于加法。
第一份手工 release 没有旁挂，**不补**：已发布的资产不可变（CONTRACT §13 L6 的精神）。

这里**不出** CONTRACT §2 形状的 `manifest.json`（`tool`/`version`/`artifacts[]`）：本仓的 `manifest.json` 名字相同，
但它是 oh 的消费契约，字段完全不同。这一点在附录 A 里作为 CONTRACT 的一处措辞缺口提出。

## 5. 幂等

| 情形 | tag 发布跑 | dispatch 空跑 |
|---|---|---|
| 该名字的 release **已发布** | `guard` 报 `::notice::` 并**成功退出**，不构建、不碰 release。已发布的资产不可变，重跑就是空操作 | 报警，照常构建（空跑本来就是看产物） |
| 该名字有 **draft**（上一次发布中途死了） | **失败**，并在消息里给出修法（看一眼 → `gh release delete <tag> --yes`，tag 保留 → re-run）。自动删 release 由人来做 | 报警 |
| 不比 latest 新 | **失败**（V3） | 报警 |
| 构建期间同名 release 冒了出来 | `publish` 失败，不碰它 | — |

**为什么先建 draft 再转正**：`gh release create` 是先建 release、再逐个上传资产。如果直接建成正式 release，
上传死在半路就会留下一个缺资产的「latest」，oh 会取到一个 asset 404 的 manifest。draft 永远不会成为 latest。
**并发**：workflow 级 `concurrency: pack`，同一时刻只有一个在跑。GitHub 只保留一个排队中的 run，
更早排队的那个会被取消。发包频率很低，这可以接受；被取消的 tag run 重新 re-run 即可。

## 6. `permissions`

顶层 `contents: read`；`build` job 显式写 `contents: read`（`gh release view` 读公开仓的 release 够用）；
`publish` job 写 `contents: write`，这是 job 级块，会**替换**顶层块（CONTRACT §4 的两条机制）。
**没有** artifact 清理 job：CONTRACT §11 那个清理 job 要 `actions: write`，超出任务书「其余 job 一律 read」的边界。
`retention-days: 1` 已经保证 artifact 一天后过期，约 21 MB。不需要任何 secret（CREDENTIALS：`GITHUB_TOKEN`
可以发本仓自己的 release）。

## 7. 维护者流程

```bash
cd ~/code/oh-docs-corpus
# 0. 本地门禁（CLAUDE.md）
actionlint && python3 -I tools/build-docs-corpus.py --self-test
# 1. 看看 master 现在会打出什么名字（只发 1 次 GET，什么都不写）；同时检查是否比 latest 新
curl -fsSL -o /tmp/latest.json https://github.com/downsea/oh-docs-corpus/releases/latest/download/manifest.json
python3 -I tools/build-docs-corpus.py --resolve --previous-manifest /tmp/latest.json --require-newer
#    指定 commit：加 --commit <7-40 hex>
# 2.（可选）空跑：改了 workflow 或脚本以后才需要，平时不必
gh workflow run pack.yml -R downsea/oh-docs-corpus [-f commit=<hex>]
gh run watch -R downsea/oh-docs-corpus
# 3. 发布：tag 就是 resolve 打印的名字
git tag -a openharmony-zh-cn-<YYYYMMDD>-<commit8> -m 'openharmony-zh-cn-<YYYYMMDD>-<commit8>'
git push origin openharmony-zh-cn-<YYYYMMDD>-<commit8>
gh run watch -R downsea/oh-docs-corpus
```

## 8. 实测读数与未验项

**已验（oh-vm，2026-10-27）**：

- 自检 `self-test: ok`，Python 3.15、3.11、3.10 都通过（3.10 = ubuntu-22.04 的系统 python3，从版本号推断）。
- `--resolve`：master → `bb01ec29`（2026-10-27T15:37:14+08:00）；`--commit aad3246e` 和全长 sha 都 →
  `openharmony-zh-cn-20261027-aad3246e`，与第一份 release 同名；`deadbeef` → gitcode 404，干净地停下。
- `--verify` 跑在**已发布的**第一份包上（`gh release download` 到 `~/.cache/oh-docs-corpus-ci/published/`）：
  全绿，5,964 篇、20,555,369 B、sha256 `c266434e…f148`，下限 5,368；`newer_than_previous: false`（同一个包，符合预期）。
  没有 `pages.tsv`，所以逐篇 sha1 复核这一项没有在真数据上跑。
- guard 步骤的 bash 抽出来在本机按六种事件模拟（dispatch 空/前缀/非法输入；tag 已发布/日期不符/新 commit）：
  分支走向、`GITHUB_OUTPUT`、摘要都符合 §5 的表。
- `actionlint` 1.7.12（带 shellcheck）零 findings；YAML 可以 parse。

**只有真跑一次 workflow 才能证明**：

- U1 GitHub runner（境外）到 gitcode 的耗时、失败率，以及是否被限流或区别对待；`timeout-minutes: 60` 够不够。
- U2 `gh release view` 在只有 `contents: read` 的 `GITHUB_TOKEN` 下能不能看到 **draft**（draft 只对有写权限的人可见；
  看不到的话，`build` 会把 draft 当成「没有」。`publish` job 的 token 有写权限，会在复核时拦住）。
- U3 `gh release create --verify-tag --draft` 后 `gh release edit --draft=false --latest` 是否像预期那样把它标成 latest；
  读回步骤 V10 就是来测这一点的。
- U4 公开仓的分钟是否真的不计入账号额度（`fed bill ci --by repo`）。
- U5 runner 上的 zlib 打出的 zip 与本机字节是否相同。**不影响正确性**：manifest 描述的就是实际打出来的那个文件；
  但同一个 commit 在两处打包，sha256 可能不同。
- U6 tag 过滤 `openharmony-zh-cn-[0-9]+-[0-9a-f]+` 会不会误配或漏配（guard 里还有一道严格的 bash 正则兜底）。

---

## 附录 A：ci-workflows issue 草稿（由主会话决定是否立条，本仓不写入 ci-workflows）

> **标题**：`docs: CONTRACT / ONBOARDING say nothing about a PUBLIC caller or a data-pack release (oh-docs-corpus)`
>
> **Status**: `needs-triage`
>
> **发现上下文**：oh-docs-corpus 的 CI 接入（本研究件，2026-10-27）。这个仓是公开仓，发布的是数据包，不是二进制。
>
> **缺口**：
> 1. **公开调用方根本用不了 `@v1`。** GitHub 不允许公开仓调用私有仓的复用 workflow（文档 *Reusing workflow configurations*）。
>    ONBOARDING §1 把「私有仓」写成前提，但没说清公开仓接入时该怎么办。这样的仓只能自己写 workflow，
>    却没有一份「公开调用方必须遵守的规则子集」可以引用。oh-docs-corpus 只能在自己的 workflow 头注里逐条点名硬规则 4/5/7/8/9/10。
> 2. **CONTRACT §1/§2 的 `manifest.json` 与数据包同名不同义。** §1 说「every release published by these workflows」，
>    范围其实限于本仓的 workflow，但 `manifest.json` 这个名字容易让 nan-fedora 侧的读取者误认。
>    建议在 §1 加一句：不由这些 workflow 发布的 release（比如 oh-docs-corpus）不受 §1/§2 约束，它们的 `manifest.json` 是另一份契约。
> 3. **§6.1 的分钟带没有区分公开仓**：公开仓的标准 runner 免费（计费文档）。如果 `fed bill ci` 把公开仓也算进带内，
>    会高估用量（待第一次真跑后用 U4 核实）。
> 4. **CREDENTIALS §4 的清单**可以加一行「oh-docs-corpus：无 secret（公开仓，`GITHUB_TOKEN` 发本仓 release）」，
>    让「哪个仓有哪些凭据」这一表保持完整。
>
> **期望**：ONBOARDING §1 加「公开仓 / 非二进制」一行：「不接复用 workflow；caller-owned workflow 须遵守硬规则 4/5/7/8/9/10 和 CONTRACT §6 的 dry-run 语义」。
> CONTRACT §1 加上述范围句。不加新的 workflow（B 被否，见本研究件 §1）。
>
> **Exit**：ONBOARDING 和 CONTRACT 的这两处措辞落地，`tools/check-docs.py` 保持绿；oh-docs-corpus 的 `pack.yml` 头注改成引用那一节，不再逐条罗列。
>
> **反向链接**：oh-docs-corpus `docs/research/2026-10-27-ci-for-docs-packs.md`；oh-cli ADR-0109 / #741。
