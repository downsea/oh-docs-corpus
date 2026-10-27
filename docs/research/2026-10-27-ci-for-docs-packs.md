# 数据包的 CI：OpenHarmony 文档包在本机打包，由 GitHub Actions 验证并发布（2026-10-27）

**结论先行**：采用 **A**。oh-docs-corpus 自己持有一个调用方 workflow，即 `.github/workflows/pack.yml`，
按家族硬规则和 CONTRACT 里适用的条款来写，不往 ci-workflows 加复用 workflow。决定这一点的事实是：
GitHub 不允许公开仓调用私有仓里的复用 workflow，而 ci-workflows 是私有仓（§1）。
打包脚本的正本搬进本仓 `tools/build-docs-corpus.py`，因此全程不需要任何 secret（§2）。

**路线经过三次实测后有变更（§9，维护者 2026-10-27 裁定）**：GitHub runner 跑不完逐篇拉取，
原因是 gitcode 的 raw 主机在 runner 列完目录后就回 418。现行路线如下：

- 维护者**在本机打包**，把 zip、`.sha256`、`manifest.json` 上传成 **draft release**，然后推 tag，
  tag 名逐字等于 release 名 `openharmony-zh-cn-<YYYYMMDD>-<commit8>`。
- CI **只做验证和发布**，不再从 raw 拉页面：
  1. 下载 draft 的资产；
  2. 用约 130 个 API 请求取 gitcode 在该 commit 的递归目录树；
  3. 逐篇核对 git blob sha1，检查页集合相等、页数不低于下限、比 latest 新；
  4. 核对 manifest、sha256、资产名、`.sha256`；
  5. 全部通过才转正并标为 latest，再按 oh 用的 URL 把 manifest 读回来。
- 任何一项不符，draft 都保持为 draft，并报出原因。`workflow_dispatch` 只做同样的验证，不发布（§3–§7）。

- **起因**：主会话任务书（2026-10-27）。第一份包 `openharmony-zh-cn-20261027-aad3246e` 是维护者手跑脚本、
  手工发布的；oh-cli ADR-0109 把这个公开仓定成 `oh docs update --corpus openharmony` 的主路。
- **范围**：本仓的 CI 形态、脚本归属、触发、校验、幂等、权限。**消费契约不动**：manifest 字段
  `{corpus, lang, source, commit, committed_at, documents, bytes, sha256, license, asset}`、
  资产名规则、zip 布局，均以 oh `src/docs_corpus/update.rs::check_release_manifest` 为准。
- **实测环境**：oh-vm（aarch64 openEuler，经代理）与 GitHub-hosted `ubuntu-22.04`，日期 2026-10-27。
  现行 `pack.yml` 还**没有**在 GitHub 上跑过，未验项见 §8。
- **措辞**：本仓文件 vendor-neutral（`CLAUDE.md` 硬规则 7）。

## 1. A 还是 B

| | (A) 本仓自己的调用方 workflow | (B) ci-workflows 新建复用的 `data-pack-release.yml` |
|---|---|---|
| **本仓能否调用** | 能 | **不能**。GitHub 文档 *Reusing workflow configurations*（2026-10-27 读）：公开仓只能调用公开仓里的复用 workflow；私有仓里的复用 workflow 只对 Access 设置放行的**私有**仓开放。ci-workflows 是私有仓，ONBOARDING §1 也把「私有仓」列为整套流水线的前提。此条只读了文档，未实际试过 |
| 「One fix, every caller」 | 只有一个调用方，不存在「N 份漂移的拷贝」 | 只有一个消费方时，这条原则得不到任何回报 |
| 「a tool's own build logic stays in the caller」 | 打包和验证逻辑（gitcode 目录树、sha1、zip 布局）本来就归本仓 | 复用 workflow 最多只能「跑调用方给的命令、发调用方给的文件」。中心仓只多出一层接口，还要承担 `v1` 移动的爆炸半径 |
| 代价 | 家族规则在这里多一份**遵守**副本（不是实现副本），缺口见附录 A | 要么把 ci-workflows 转成公开仓，要么另开一个公开的复用仓，两者都会改变家族的安全前提 |

**推荐 A。** 即使 ci-workflows 是公开仓，只有一个消费方时 B 也不值得做。等出现第二个数据包调用方时再议，
那时先确认它是公开仓还是私有仓。

A 并不脱离家族规范。`pack.yml` 的头注逐条点名它遵守的规则：

- 硬规则 4：`.sha256` 的格式。
- 硬规则 5：只用 ubuntu-22.04。
- 硬规则 7：无 secret，不用 `set -x`。
- 硬规则 8：不写读端会先退出的管道。
- 硬规则 9：权限范围见 §6。
- 硬规则 10：现行路线不产生 artifact，这一条自然满足。

actions 的钉法照 ci-workflows 现有 workflow 的做法，按主版本钉（`actions/checkout@v5`）。
发布用 runner 自带的 `gh`，不用第三方的 release action：这样少一个持写权限 token 的第三方组件，
而且 `--verify-tag`、`--draft=false`、`--latest` 都可以直接传参。

## 2. 打包脚本的归属

**推荐：正本搬进本仓 `tools/build-docs-corpus.py`；oh-cli 删掉 `scripts/build-docs-corpus.py`，改为指向这里。**

| | 利 | 弊 / 风险 |
|---|---|---|
| 正本在本仓 | workflow 检出本仓就拿到脚本，**零 secret**（不需要 `SIBLING_TOKEN`）。公开仓里的脚本人人可审；语料是 CC BY 4.0 再分发，可审本身就是好事 | **NOTICE 文本、资产名规则、zip 布局是跨仓契约**：oh 的 gitcode 后备路必须产出同样的形状（`oh_notice` 与 `notice()` 逐字节相同）。耦合从「同仓两份」变成「跨仓两份」 |
| 留在 oh-cli（私有）| 与 `oh_notice` 同仓 | CI 读私有仓需要 `SIBLING_TOKEN`，违背零 secret；或者手工同步拷贝，必然漂移 |

**怎么压住跨仓漂移**：两边各自钉住同一份字节。

- oh 侧：`src/docs_corpus/update/tests.rs` 里有 NOTICE 的字面量断言。
- 本仓：`--self-test` 里的 `NOTICE_GOLDEN_SHA256`，已与 oh 的字面量逐字核对过（oh-vm，2026-10-27）。
  manifest 字段集合由 `MANIFEST_KEYS` 钉住。

**脚本的构建行为不变**：manifest 字段、资产名、zip 布局、取数步骤都没动。新增的参数全部可选：

- `--resolve [--shell]`
- `--verify DIR`，可配 `--against-gitcode` 或 `--pages-tsv`
- `--min-documents`、`--previous-manifest`
- `--expect-asset`、`--require-newer`、`--require-sidecar`

`--commit` 现在也接受 7–40 位的前缀。主会话后来又加了 `Http.get` 的重试（commit `cb6719d`、`b329d57`）：
超时、连接错误、5xx、429、418 都会重试，418 的退避是 15/30/60 s。

**顺带修了一个既有缺陷**：原脚本的 `--commit <sha>` 解析走的是 `GET commits/<sha>`，而 gitcode 这个单条接口的应答
**不带 `commit.tree`**（oh-vm 实测，2026-10-27）。所以只要指定 commit，构建必然失败。
现在改走 `commits?sha=<ref>&per_page=1`，它带 tree，并且接受分支、全长 sha 和前缀；
另外检查应答的 sha 是否以所请求的前缀开头。oh 自己只用 `sha=master`，不受影响。

## 3. 触发模型（现行）

| 事件 | 做什么 | 发不发 |
|---|---|---|
| 推 tag `openharmony-zh-cn-<YYYYMMDD>-<commit8>`（filter `openharmony-zh-cn-[0-9]+-[0-9a-f]+`，guard 里再用严格正则确认） | 验证同名 **draft** release | 全部通过才发；已发布则什么都不做；没有 draft 则失败 |
| `workflow_dispatch`（输入 `tag`，为空时取 `releases/latest`） | 同样的验证，对象可以是 draft 或已发布的 release | **从不发布**（CONTRACT §6） |
| push / PR / schedule | 无 | — |

**为什么 tag 名必须逐字等于 release 名**：这和 CONTRACT §6「tag 逐字是 `v<version>`」是同一个思路。
发布什么，看 tag 就知道；tag 指向的本仓 commit 同时也钉住了验证脚本的版本。
CI 用 `--expect-asset <tag>.zip` 强制 manifest 的 `asset` 等于这个名字，而 `asset` 由 commit 和日期算出，
gitcode 又会核对这对 commit 和日期。所以 tag、manifest、gitcode 三者必须相互一致。

**draft 和 tag 的先后：先建 draft，再推 tag。**

- 推 tag 就是触发器，CI 一启动就要找到 draft。反过来做，这一次 run 必然因为「no draft」失败，只能补传后 re-run。
- 为一个还不存在的 tag 创建 draft 是可以的：GitHub 的 draft 只记录 `tag_name`，tag 由维护者随后自己推送。
  转正时 `--verify-tag` 会确认 tag 已经在远端。
- draft 对外不可见，也永远不会成为 `releases/latest`，所以先建 draft 不会暴露给 oh 的用户。

**分钟成本**：一次发布是一条 ubuntu 腿，主要耗时在列目录树（runner 上约 10 分钟，见 §9）。
本仓是公开仓，按 GitHub 计费文档，标准 runner 免费，不计入 Pro 的 3000 分钟（账单上尚未核实，U4）。
**gitcode 负载**：每次约 130 个 API 请求，不碰 raw，是原路线的约 2%。

**不开定时任务**：现行路线里打包在人手上，定时任务没有东西可跑。即便以后在别处自动打包，
无人值守地把新包推成 `releases/latest` 也会直接改变所有用户的结果，需要另做裁定。

## 4. 发布前校验（`--verify DIR --against-gitcode`，CI 与本机共用）

任何一项红，CI 就以非零退出码结束，draft 保持为 draft，原因写进 `::error::` 和 step summary。

| # | 检查 | 防的是 |
|---|---|---|
| V1 | `--self-test`：离线，合成 gitcode；覆盖 NOTICE 金样、目录树/页集合/日期漂移，以及校验器的每一条失败路径 | 脚本本身坏了 |
| V2 | release 名 = tag，并且 = manifest 的 `asset` 去掉 `.zip`（`--expect-asset`） | 发出的东西与 tag 不符 |
| V3 | gitcode 用该 commit 回答的 sha 和 `committed_at` 必须与 manifest **完全相同** | manifest 写错 commit 或日期 |
| V4 | **逐篇 git blob sha1**：zip 里每一篇都要与 gitcode 目录树里同一路径的 sha 相等，两边的路径集合也要相等 | 打包时页面被篡改、漏页、多页 |
| V5 | **页数下限** = max(5000, ⌈0.9 × latest.documents⌉) | 残缺的包（今天 5,964 → 下限 5,368） |
| V6 | **必须比 latest 新**：`committed_at` 更晚，且 commit 不同（只在发布时强制） | 发一个旧 commit，会让所有用户退回旧文档 |
| V7 | manifest 的字段集合**恰好**是那 10 个；固定字段的值正确；`bytes`、`sha256`、`documents` 与实物一致 | 消费契约漂移 |
| V8 | zip：CRC 校验；`LICENSE` 和 `NOTICE` 排在最前；只含 `docs/**.md`；路径安全、有序、无重复；deflate 且无 data descriptor；NOTICE 逐字节正确；LICENSE 是 CC BY 4.0 原文 | oh 的读取器拒收，或署名不对 |
| V9 | oh 消费侧的上限：zip ≤ 256 MiB、条目 ≤ 64,000、单篇 ≤ 4 MiB、解压总量 ≤ 512 MiB（oh `001439b7`） | 能发出去，但在每个用户那里都失败 |
| V10 | `.sha256` **必须存在**（`--require-sidecar`），内容逐字节等于 `<hash>` + 两个空格 + `<file>` + LF；另外跑一次 `sha256sum -c` | 旁挂缺失或格式不对 |
| V11 | draft 只能有这 3 个资产 | 混入别的文件 |
| V12 | 转正前，用 `gh release view --json assets` 再读一次 draft：仍是 draft，资产名集合不变，每个资产的 `digest` 等于刚才验证过的那份字节的 sha256 | 下载之后、转正之前 draft 被人改动（TOCTOU） |
| V13 | 转正后按 oh 的 URL 读回 `releases/latest/download/manifest.json`，必须逐字节相同（只报警，因为已经公开，撤不回） | latest 标记没生效，或缓存滞后 |

多出一个 `<asset>.sha256` 资产，不会破坏 oh：oh 只取 `manifest.json` 以及其中 `asset` 指向的文件，不枚举 release 资产。
第一份手工 release 没有旁挂，这里**不补**，因为已发布的 release 不可变。
本仓的 `manifest.json` 与 CONTRACT §2 里的 manifest 同名不同义，见附录 A。

## 5. 幂等

| 情形 | tag 发布 run | dispatch 验证 run |
|---|---|---|
| 该名字的 release 已发布 | `::notice::`，成功退出，什么都不碰（不可变） | 照常验证 |
| 是 draft | 验证，通过则转正 | 验证，不转正 |
| 不存在 | **失败**：提示先 `gh release create … --draft`，再 re-run | 失败 |
| 验证红 | 失败，draft 保持为 draft；修好后可以**删 draft 重传**（`gh release delete <tag> --yes`，tag 保留），再 re-run | 失败 |
| 转正前 draft 被改 | 失败（V12），不碰它 | — |

**并发**：workflow 级 `concurrency: pack`，同一时刻只跑一个。

## 6. `permissions`

顶层是 `contents: read`。唯一的 job `verify` 是 `contents: write`。原因是：draft release 只对有 push 权限的 token 可见
（GitHub REST 文档，*List releases*：只有拥有 push 权限的用户才会在列表里看到 draft）；同一个 job 还要把 draft 转正。
dispatch 验证也需要这个权限，因为它也要能读 draft；它从不转正，转正那一步的 `if` 只对 tag 事件成立。
任务书原本是「发布 job 写、其余只读」，这里收成一个 job。收紧之后的做法是：写权限只用于 `gh release edit` 这一条命令，
不上传、不删除、不建 artifact。不需要任何 secret。

## 7. 维护者流程（每次发版）

```bash
cd ~/code/oh-docs-corpus && git pull --ff-only
W=~/.cache/oh-docs-corpus-ci && mkdir -p "$W"             # 不用 /tmp（tmpfs）
curl -fsSL -o "$W/latest.json" https://github.com/downsea/oh-docs-corpus/releases/latest/download/manifest.json

# 1. 定名（1 次 GET）；比 latest 旧就在这里停下。指定 commit：加 --commit <7-40 hex>
eval "$(python3 -I tools/build-docs-corpus.py --resolve --shell --previous-manifest "$W/latest.json" --require-newer)"
echo "$TAG $COMMIT"

# 2. 打包（约 8.5 分钟，约 6,100 次 GET）
python3 -I tools/build-docs-corpus.py --out "$W/$TAG" --commit "$COMMIT" \
  --min-documents 5000 --previous-manifest "$W/latest.json" --pages-tsv "$W/$TAG.pages.tsv"
(cd "$W/$TAG" && sha256sum "$ASSET" > "$ASSET.sha256")

# 3. 本机先跑一遍 CI 会跑的验证（约 130 次 GET）
python3 -I tools/build-docs-corpus.py --verify "$W/$TAG" --against-gitcode --require-sidecar \
  --min-documents 5000 --expect-asset "$ASSET" --previous-manifest "$W/latest.json" --require-newer

# 4. 上传成 draft（对外不可见），再推 tag = 触发 CI 验证并转正
gh release create "$TAG" -R downsea/oh-docs-corpus --draft --title "$TAG (draft)" \
  --notes "draft — verified and published by the pack workflow" \
  "$W/$TAG/$ASSET" "$W/$TAG/$ASSET.sha256" "$W/$TAG/manifest.json"
git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"
gh run watch -R downsea/oh-docs-corpus

# 5. 确认（oh 读的就是这个 URL）
curl -fsSL https://github.com/downsea/oh-docs-corpus/releases/latest/download/manifest.json
```

CI 转正时会用 manifest 生成的标题和 notes 覆盖 draft 上的标题和 notes。只验证、不发布：
`gh workflow run pack.yml -R downsea/oh-docs-corpus [-f tag=<名>]`。

## 8. 实测读数与未验项

**已验（oh-vm，2026-10-27）**：

- `--self-test` 在 Python 3.15、3.10 下都通过（3.10 = ubuntu-22.04 的系统 python3，按版本推断）。
- **对已发布的第一份包做 `--verify --against-gitcode`**：全绿。**5,964 / 5,964 篇的 blob sha1 与 gitcode 目录树一致**，
  commit 和日期由 gitcode 确认，下限 5,368，耗时 81 s（主要花在列目录树）。
- 把 workflow 里的「Verify」步骤原样抽出，在本机对这份包跑了两遍：dispatch 模式通过；
  发布模式按 V6 拒绝（同一个包不比自己新），summary 里写明了原因。
- 把「Publish」步骤里的 V12 核对脚本抽出来单独跑：对已发布的 release 拒绝（`isDraft=False`）；
  对模拟的 draft JSON 通过。真实 release 的 `gh --json assets` 带 `digest` 字段（已读到）。
  这一步**没有执行 `gh release edit`**。
- 「Plan」步骤在本机模拟了 5 种事件：dispatch 取 latest、dispatch 指定不存在的名字、tag 已发布、tag 无 draft、tag 名非法。
  分支走向都与 §5 一致。
- `actionlint` 1.7.12（带 shellcheck）零 findings；YAML 可以 parse。

**只有真跑一次 workflow 才能证明**：

- U1 runner 上列目录树的耗时：之前读到约 10 分钟，`timeout-minutes: 40` 预计够用；API 请求会不会也被 418，未知。
- U2 `contents: write` 的 `GITHUB_TOKEN` 能否用 `gh release view/download <tag>` 读到 **draft**（按文档应当可以）。
- U3 `gh release create --draft` 能否为远端尚不存在的 tag 建 draft；推 tag 后，`gh release edit --verify-tag --draft=false --latest`
  能否把它挂到这个 tag 上并标为 latest。
- U4 公开仓的分钟是否真的不计入账号额度（`fed bill ci --by repo`）。
- U5 draft 资产在 `--json assets` 里是否也带 `digest`。如果为空，V12 会**拒绝转正**，这是安全的失败方向，但需要改代码。

## 9. 三次实测与路线变更（2026-10-27）

第一版 `pack.yml`（commit `d00926d`）的设计是 CI 在 runner 上完整打包：guard、构建、`--verify --pages-tsv`、
artifact、draft、转正。主会话推到 main 后实测如下：

| run | 结果 | 读数 |
|---|---|---|
| 40469004197 | 72 s 失败 | 解析目录树时读超时，当时这一步没有重试 → 主会话 `cb6719d`：所有 GET 都会重试（超时、连接错误、5xx、429） |
| 40469395436 | 613 s 失败 | runner 列完 5,964 篇用了**约 10 分钟**（oh-vm 44 s），紧接着第一个 raw 请求就回了 **418** |
| 40470642335（probe，已删） | 200 | 换一个新 runner，单个 raw 或 API 请求都是 200，耗时约 2 s。**418 是请求量触发的限流，不是 IP 被封** → 主会话 `b329d57`：把 418 当成限流，退避 15/30/60 s |
| 40470785867 | 60 分钟处被 **cancelled** | 有了退避，逐篇拉取在时限内还是拉不完 |

**判断**：境外 runner 到 gitcode 的单请求延迟高（约 2 s），raw 主机又会在大约 130 次请求后对后续请求回 418。
按约 6,000 次请求加上退避来算，一次构建远远超过一小时。这不是重试参数调得不对，而是这种请求量在 runner 上走不通。
oh-vm 上同样的构建是 8.5 分钟，从没遇到过 418。

**维护者裁定（2026-10-27）：本机打包，CI 只验证和发布**（§3–§7）。验证之所以仍然有意义：
gitcode 目录树是独立于打包人的第三方事实。CI 不必信任上传者，只需证明「这个 zip 的每一页都正好是 gitcode 在该 commit 的那一篇」。
这与在 CI 里重新打包给出的保证相同，只是少了约 6,000 次 raw 请求。
留下的风险是列目录树的 130 次 API 请求本身也可能被限流（U1）。

---

## 附录 A：ci-workflows issue 草稿（由主会话决定是否立条，本仓不写入 ci-workflows）

> **标题**：`docs: CONTRACT / ONBOARDING say nothing about a PUBLIC caller or a data-pack release (oh-docs-corpus)`
>
> **Status**：`needs-triage`
>
> **发现上下文**：oh-docs-corpus 的 CI 接入（本研究件，2026-10-27）。这是一个公开仓，发布的是数据包，不是二进制；
> 构建在开发机上完成，CI 只做验证和发布（§9）。
>
> **缺口**：
> 1. **公开调用方根本用不了 `@v1`**。GitHub 不允许公开仓调用私有仓的复用 workflow。ONBOARDING §1 把「私有仓」写成前提，
>    却没有一份「公开调用方必须遵守的规则子集」可以引用，所以 oh-docs-corpus 只能在 workflow 头注里逐条点名硬规则 4/5/7/8/9/10。
> 2. **CONTRACT §1/§2 的 `manifest.json` 与数据包的同名不同义**。建议在 §1 加一句：不由这些 workflow 发布的 release
>    （例如 oh-docs-corpus）不受 §1/§2 约束。
> 3. **§6.1 的分钟带没有区分公开仓**：公开仓的标准 runner 免费（计费文档）。待第一次真跑后核实。
> 4. **「CI 只验证、构建在开发机」这种形态**与 §13 本地发布有相通之处（构建在开发机），但又不同：这里是 CI 守门，再由 CI 转正。
>    §13 没有覆盖这种「draft + CI 守门」的模式，可以作为一种已知的形态记一笔。
> 5. **CREDENTIALS §4 的清单**可加一行：oh-docs-corpus 无 secret（公开仓，`GITHUB_TOKEN` 发本仓 release）。
>
> **期望**：ONBOARDING §1 加「公开仓 / 非二进制」一行；CONTRACT §1 加上述范围句。不加新的 workflow（B 被否，见 §1）。
>
> **Exit**：上述措辞落地，`tools/check-docs.py` 保持绿；oh-docs-corpus 的 `pack.yml` 头注改为引用那一节。
>
> **反向链接**：oh-docs-corpus `docs/research/2026-10-27-ci-for-docs-packs.md`；oh-cli ADR-0109 / #741。
