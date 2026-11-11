# 自博弈上手指南（队友版）

这份文档只讲一件事：**你拿到一片自博弈任务之后，从配置到把结果推上 GitHub，一步一步怎么做**。为什么这样设计、玩家性格怎么生成、各模型的比例，见 [selfplay.md](selfplay.md)；人工标注见 [annotation.md](annotation.md)。

先说整体：每一轮由负责人生成一份"清单"（每一局的人格、玩家模型、DM 策略、随机种子都已经定好），切成几片，每人领一片。你要做的只有三步：**跑、打包、推送**。你不需要做任何选择，也不需要理解人格怎么抽样的。

```
负责人：生成清单 → 提交并打 tag → 通知大家
你：    检出 tag → 跑你那一片 → 打包 → 推送
负责人：校验整轮 → 出报告
```

## 1. 你需要有什么

| 项 | 要求 |
|---|---|
| 电脑 | Mac 或 Linux，能联网；跑的时候**不能休眠**（一片通常要跑几个小时，见第 8 节） |
| 软件 | git、[uv](https://docs.astral.sh/uv/)、Python 3.13（uv 会装）。不需要 Node，也不需要 git-lfs |
| API key（必需） | **DeepSeek** 和 **Moonshot（Kimi）** 各一个，用你自己的，不要借别人的 |
| 订阅（可选，但有就开） | Claude（`claude` 命令行）和 GPT（`codex` 命令行）。清单里每片都会分到少量只能由这两个模型当玩家的局；你的电脑没有，这些局会被跳过并列出来，见第 5 节 |
| 磁盘 | 一片 100 局大约 60 MB（压缩后约 5 MB） |
| 费用 | 每局约 $0.2 到 0.3（API 花费，全部在 DeepSeek 和 Moonshot 上），见第 8 节 |

## 2. 一次性配置（约 10 分钟）

```bash
git pull
cd backend
uv sync
cp .env.selfplay.example .env       # 已经有 .env 的话，把里面两个 key 的行加进去即可
```

打开 `backend/.env`，填两行：

```
DEEPSEEK_API_KEY=你的 key
MOONSHOT_API_KEY=你的 key
```

`.env` 已被 gitignore，**不要提交，也不要发到群里**。模型的名字、端点、价格都在 `backend/selfplay/profiles.yaml`（提交进仓库的，全组一致），你不用也不要改它。

如果你有 Claude 或 GPT 订阅，各登录一次：

```bash
claude /login            # 选第 1 项 "Claude account with subscription"，不要选 API usage billing
codex login              # 用 ChatGPT 账号登录；codex login status 可以看状态
```

然后检查配置：

```bash
uv run python -m selfplay doctor --probe
```

`--probe` 会真的让 claude 和 codex 各回答一次（几秒钟，花一点点订阅额度）。**不加 `--probe`，doctor 只检查命令装没装，不验证登录**，登录过期时也会显示 ok。输出长这样：

```
  ok  profile: deepseek-flash    reachable, key accepted
  ok  profile: kimi-k2.6         reachable, key accepted
  ok  profile: claude            2.1.x (Claude Code) answered in 3s
  NO  profile: gpt               codex did not answer: ...
This machine can play sessions whose player is: claude, deepseek-flash, deepseek-v4-pro, kimi-k2.6.
```

最后一行说的是**这台电脑能跑哪些局**。NO 的项不影响其他局，但要么修好它，要么跑完后把被跳过的局告诉负责人（第 5 节）。引擎本身用到的几个模型（DeepSeek、Kimi）只要有一个是 NO，就一局都跑不了，必须先修。

## 3. 负责人做的事（你不用做）

负责人为每一轮做三件事，做完会在群里通知你，通知里有轮次名（下面以 `r1` 为例）：

1. `uv run python -m selfplay manifest --round r1 --n 30 --shards 6`：生成清单 `backend/selfplay/manifests/r1/`，其中 `shard-01.json` 到 `shard-06.json` 是每人的那一片。同一个轮次名永远生成同一份清单，已经存在会拒绝覆盖。
2. 提交清单并打 tag：`git tag selfplay-r1`，然后连 tag 一起推送（`git push` 和 `git push origin selfplay-r1`）。队友 `git fetch --tags` 之后才看得到这个 tag。
3. 全部跑完后：`uv run python -m selfplay check r1`（校验）和 `report r1`（统计报告）。

**在负责人通知你之前，不要自己运行 `manifest`。** 你的片是哪一个（`shard-03` 这样的编号），也在通知里。

## 4. 每一轮你要做的

### 4.1 检出这一轮的版本

```bash
git fetch --tags
git checkout selfplay-r1        # 会提示 detached HEAD，这是对的
cd backend
uv sync
```

**所有人必须用同一个 tag 的代码跑**。`check` 会拒收记录的 git commit 不等于本轮 tag 的局，所以别在别的分支上跑，也别在跑的过程中改任何文件。

### 4.2 跑

```bash
uv run python -m selfplay run --shard selfplay/manifests/r1/shard-03.json --budget-usd 8
```

把 `shard-03` 换成你的片。它会：

- 每开始、结束一局打印一行：局号、玩家模型、DM 策略、状态、结局、回合数、耗时、花费；
- 在 `backend/data/selfplay_raw/r1/shard-03/` 下为每局建一个文件夹，所有记录都在里面（这个目录不进 git）；
- 费用累计到 `--budget-usd` 就不再开新局，超过 25% 会中止正在跑的局（它们下次会重跑）。**预算按"你的局数 × $0.4"估**，上面的 8 对应 20 局左右；
- 默认同时跑 6 局，Claude 和 GPT 的局固定一次一局。

常用选项：

| 选项 | 用途 |
|---|---|
| `--concurrency 3` | 同时跑几局。出现大量 429（限流）报错时调低 |
| `--max-sessions 5` | 这次只开始 5 局，用来先试一试速度 |
| `--retry-errors` | 重跑上次状态是 error 的局（见第 5 节） |
| `--session r1-0042` | 只跑某一局，可重复写多个 |
| `--budget-usd N` | 费用上限，到了就停，不会多花 |

**不要加 `--allow-dirty`**（它是给本地调试用的，加了之后跑出来的局会被 `check` 拒收）。如果 `run` 说"工作区有未提交的改动"，说明你改过文件，先 `git status` 看看改了什么，用 `git stash` 暂存。

**让电脑别休眠**：Mac 上在命令前面加 `caffeinate -i`：

```bash
caffeinate -i uv run python -m selfplay run --shard selfplay/manifests/r1/shard-03.json --budget-usd 8
```

终端窗口不要关；合上笔记本盖子等于休眠。

### 4.3 看进度、中断和续跑

- 屏幕上的 `ended` 行就是跑完一局。`max_turns` 也算完成（这一局打满了 60 回合），`error` 是出错了（第 5 节）。
- **中断了（Ctrl-C、断网、休眠）没关系**：重新运行**同一条命令**，已经完成的局会跳过，没跑完的局整局重跑，不会重复花钱（已经调用过的结果会缓存）。
- 跑完时会打印一段汇总，重点看 `statuses`（各状态各几局）、`unavailable`（被跳过的局）、`not_started_budget`（因为预算到了没开始的局）、`spent_usd`（花费）。三个列表都是空的、`statuses` 里全是 `ended` 或 `max_turns`，就是完整跑完了。

屏幕上偶尔出现的 `llm ... failed` / `llm ... unusable` 警告行是正常的（模型偶尔超时或返回格式不对，系统会自动重试或换模型）。如果**连续刷屏**，才说明有问题，见第 5 节。

### 4.4 打包并推送

```bash
uv run python -m selfplay pack --shard selfplay/manifests/r1/shard-03.json
```

它会把已经跑完的局各压成一个 `.tar.gz`，写到 `backend/data/selfplay/r1/shard-03/`；没跑完的局不会打包，会列在输出里。然后**回到 main** 提交：

```bash
git switch main
git pull --rebase
git add backend/data/selfplay/r1/shard-03
git commit -m "selfplay r1 shard 03"
git push
```

打包的数据文件是新增的未跟踪文件，切回 main 时会原样保留；每个人只写自己那一片的目录，所以不会冲突。**推送成功之前，不要删 `backend/data/selfplay_raw/`**，那是你唯一的原始记录。

## 5. 出问题怎么办

| 你看到的 | 原因 | 怎么办 |
|---|---|---|
| `Failed to authenticate: OAuth session expired and could not be refreshed` | claude 或 codex 的登录过期了 | 重新登录（第 2 节），用 `doctor --probe` 确认后，用 `--retry-errors` 重跑 |
| `429 ... account ... is suspended due to insufficient balance` | DeepSeek 或 Moonshot 账户没钱了 | 充值；这条不会被 doctor 发现（key 是有效的，只是没余额）。充值后 `--retry-errors` |
| 某一局几秒钟就 `error`，`error` 字段写着 "the player model failed 3 turns in a row" | 玩家那个模型一直调不通（登录、余额、网络） | 看 `selfplay.json` 里的 `error`，修好原因后 `--retry-errors`。系统故意让它早停，不让它白跑一整局 |
| 汇总里有 `unavailable` | 清单里分给你的某些局，要用你电脑上没有的模型（比如没装 Claude） | 把这些局号发给负责人，换一台能跑的电脑用 `--session` 补跑；你不用管 |
| 汇总里有 `not_started_budget` | 预算到了，还有局没开始 | 想继续就调高 `--budget-usd`，用同一条命令重跑 |
| 说工作区有改动，拒绝运行 | 你改过仓库里的文件 | `git status` 看，`git stash` 暂存 |
| 一直刷 429 / 超时 | 并发太高被限流 | `--concurrency 3`，再不行 `--concurrency 2` |
| `check` 或负责人说你的局 commit 不对 | 没有在 tag 上跑 | 回到 tag 重跑这些局（`--session`） |
| 其他，或者你觉得是代码的 bug | | **不要自己改代码**。改了代码这一轮的数据就不可比了。把报错截图发给负责人，由负责人决定修了之后是否重新打 tag |

## 6. 想看看跑出来的内容

一局的所有记录在 `backend/data/selfplay_raw/r1/shard-03/<局号>/`，其中最有用的：

| 文件 | 内容 |
|---|---|
| `selfplay.json` | 状态、结局、回合数、各模型的 token 和费用、耗时、报错信息 |
| `persona.json` | 这一局玩家的人格卡、目标、立场、玩家模型和 DM 策略 |
| `player.jsonl` | 玩家每次尝试写了什么，被拒的原因 |
| `turns.jsonl` | 每回合的完整链路（玩家输入、世界规则、DM 选的 beat、叙述者的正文、guard 检查、耗时） |

直接读 JSON 不方便，可以生成可读的逐回合记录（加 `--zh` 同时生成中文版，用 deepseek 翻译，花费很少）：

```bash
uv run python -m selfplay transcript r1-0007 --round r1 --zh
```

生成的 `transcript.md` 和 `transcript.zh.md` 就在那一局的文件夹里。看整片的统计（结局分布、被拒率、费用等）：

```bash
uv run python -m selfplay report r1 --raw
```

## 7. 红线

- **不要提交 `.env`，也不要把 key 发给任何人。**
- **不要改仓库里的任何文件**：`backend/data/`、`backend/prompts/`、`backend/selfplay/` 下的任何东西都不要动。一轮之内所有人必须用同一份。
- **不要运行 `manifest`**，不要用 `--allow-dirty`。
- 不要在推送成功之前删 `selfplay_raw/`。
- 数据里没有真实个人信息（玩家的名字是随机的英文名，玩家是 LLM），可以放心提交；日志里也不会记录 key。

## 8. 时间和费用参考

来自 2026-11-09 的 10 局试跑（pilot）实测：

| 项 | 数字 |
|---|---|
| 每局时间 | 18 到 31 分钟（一局 12 到 37 回合，每回合平均约 28 秒） |
| 每局费用 | $0.12 到 0.31，平均约 $0.22，约 60 万 token |
| 同时跑 6 局 | 约每小时跑完 14 局 |
| 一片 100 局 | 约 7 小时，约 $22；建议晚上开着，用 `caffeinate -i` |
| Claude、GPT 的局 | 一次一局，每局约 20 到 30 分钟，订阅额度，不花 API 费（引擎部分仍用 DeepSeek，约 $0.2 一局） |

时间主要花在叙述者和 guard 上，不是你的电脑，换一台快的电脑不会明显更快。

## 9. 还有疑问

- 为什么用这些模型、为什么一局只用一个玩家模型、人格卡怎么来的：[selfplay.md](selfplay.md) §2 到 §6。
- 每一轮的目标和规模、什么时候进入下一轮：[selfplay.md](selfplay.md) §10。
- 数据拿来做什么（标注、训练）：[annotation.md](annotation.md)、[backend-design.md](backend-design.md)。
- 其他问题直接在群里问负责人。
