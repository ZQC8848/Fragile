# Fragile：开发计划（到 LLM mock 跑通全流程）

> v0.1 · 2026-10-06
> 目标日期：2026-10-18（对应 backend-design.md §10 时间线的第 2 周末）
> 依据：[story.md](story.md)、[interaction-design.md](interaction-design.md)、[backend-design.md](backend-design.md)。本文只管"怎么做、按什么顺序做、做到什么算完"，设计本身以那三份为准。

---

## 0. 目标与验收

### 0.1 两种 mock

| 叫法 | 是什么 | 用在哪 |
|---|---|---|
| **LLM mock** | 用真实的 LLM API 顶替将来自训练的 M1–M4，也就是每个模块的 `llm` 那一路 | 本计划的目标：游戏用它跑通 |
| **离线 mock** | 不联网、确定性的假实现（沿用 Wrongest Person 的 `mock` provider） | 单元测试和 CI；没有 API key 也能跑 |

每个 LLM 角色两种都要有。

### 0.2 "跑通"的定义（10/18 验收清单）

- [ ] **浏览器里从开局玩到结局**：输入名字和性别 → 开场 → 三种输入方式都能用（单框整理、分栏、选项） → 不合规的输入被拒并能一键改写 → 第一人称段落 → 换房间 → 用手机 → Nora 四级依次到来 → 敲门 → `testimony` → 结局。
- [ ] **四个模块都走 `llm` 路径**，`rule` 路径在影子模式下同时运行并记日志；`trained` 路径是占位，委托给 `llm`，日志里标明。
- [ ] **五个结局**都能用脚本化的路径到达。
- [ ] **自博弈**：5 种人格无头连跑 50 局不崩，产出完整日志和一份统计。
- [ ] **日志**：回合日志和决策日志齐全，能导出四个模块的数据集 v0。
- [ ] **Console**：回合检查器、决策日志、拍子架、状态、控制面板可用。
- [ ] **测试**：离线 mock 下 `pytest` 全绿，包括 golden path、无死局、每个结局可达。

### 0.3 不在本计划里

训练 M1–M4 和 `ml/` 包；新的标注界面（沿用现有的 pairwise）；插图生成（只做占位）；用户研究；剩下的约 15 个卫星拍（和本计划并行写，不卡验收）。

---

## 1. 起点：从 Wrongest Person 拿什么

代码放在 Fragile 仓库里（backend-design.md 待定项 B1 的建议）。Wrongest Person 仓库只读，不在那边改。

### 1.1 后端（`D:\OtherProjects\WrongestPerson\backend`）

| 模块 | 处理 | 说明 |
|---|---|---|
| `engine/dsl/`（parser、evaluate、effects） | 直接拷 | 标识符支持点号，`topic_tier.leo`、`turn.acts` 可以直接用；要加的内置函数在 M3 里补 |
| `engine/state/schema.py` | 直接拷 | 换成读 `state_v2.json` |
| `engine/llm/client.py` | 拷后改 | 加响应缓存、prompt 版本号、JSON 输出校验和重试 |
| `engine/beats/`（loader、pool） | 拷后改 | goals 换成步；加 `minutes`、`max_turns`、两种开场、`asks`、`outcomes`；去掉 `repeatable`；`shelf()` 保留 |
| `engine/dm/`（manager、scorers、tension） | 拷后改 | 加优先级分层和必接拍；目标弧按剧情分钟；scorer A / B / random 保留，C 占位 |
| `engine/generate/proposer.py` | 拷后改 | 按 beat v2 生成；硬检查加 `minutes` 范围 |
| `engine/journal/` | 拷后改 | 加回合日志 |
| `engine/world/rules.py` | 拷后改 | 区域换成房间；加阻拦、跟随、手机动作、`heard_by` |
| `engine/performer/` | 不要 | 由 `engine/narrator/` 重写 |
| `engine/tts/` | 不要 | |
| `app/main.py` | 拷后改 | REST 大体沿用，WebSocket 换成新协议 |
| `app/session.py` | 重写 | 订阅分发、生命周期和控制命令可以照搬；主循环换成回合循环 |
| `selfplay/` | 拷后改 | 5 种人格，输出分栏或单框，注入违规输入 |
| `tests/test_dsl.py` | 直接拷 | 其余测试按新故事重写 |
| `llm_providers.env` | **不要拷** | Wrongest Person 把 key 提交进了 git。Fragile 的 key 只放在被 gitignore 的 `.env` 里 |

### 1.2 前端（`D:\OtherProjects\WrongestPerson\frontend`）

| 模块 | 处理 |
|---|---|
| Vite + React + TS + Zustand + Tailwind 脚手架、`scripts/gen-types.mjs`、`net/ws.ts`、`net/api.ts`、`hooks/` | 直接拷 |
| `store/session.ts` | 拷后改，适配新协议 |
| `console/BeatShelf`、`tabs/DecisionLogTab`、`ControlTab`、`StateTab`、`AnnotateTab`、`panel/TensionCurve`、`JsonTree`、`CandidateList` | 拷后改 |
| `game/`（Phaser）、`portrait/`、`performance/`、`ui/DialogueUI`、`tabs/PerformanceTab`、`tabs/BeatGraphTab` | 不要 |
| Play 界面、Console 的回合检查器 | 新写（M5） |

---

## 2. 目标目录

```
Fragile/
├── story.md  interaction-design.md  backend-design.md  plan.md
├── schemas/
│   ├── state_v2.json  beat_v2.json  messages_v2.json
│   └── llm/                       每个 LLM 角色输出的 JSON Schema
├── backend/
│   ├── app/                       main.py  session.py（回合循环）
│   ├── engine/
│   │   ├── state/ dsl/ llm/ journal/          拷
│   │   ├── beats/ dm/ generate/ world/        拷后改
│   │   ├── clock/                 剧情时钟、Nora 事件
│   │   ├── input/                 整理（M2 llm）、选项生成
│   │   ├── reactions/             反应层
│   │   ├── narrator/              叙述者
│   │   ├── models/                scorer / encoder / guard / tension 三路适配
│   │   └── illustrate/            占位：只发 tableau id
│   ├── prompts/                   每个角色一个 <role>_v<N>.md；evals/<role>.jsonl
│   ├── data/
│   │   ├── beats/                 phase1.yaml phase2.yaml phase3.yaml endings.yaml
│   │   ├── knowledge/             julian.yaml mia.yaml nora.yaml player.yaml
│   │   ├── interactions.yaml  reactions.yaml  clock.yaml  tension_curve.yaml
│   │   ├── logs/  cache/          git 忽略
│   │   └── candidate_pool/
│   ├── selfplay/
│   ├── tools/                     play_cli.py  eval_prompts.py  export_datasets.py  selfplay_report.py
│   └── tests/
└── frontend/
```

---

## 3. 关键实现约定

设计文档没写到、但写代码前必须定下来的几件事。

### 3.1 一回合的执行顺序

```
review   = 整理结果（单框原样确认时复用发送前的结果，否则重新调 M2）
units    = review.units                                  # M2
world    = rules.apply(state, units)                     # 动作、换房间、跟随、阻拦、手机、heard_by
reaction = reactions.select(state, units, world)         # 主反应 + 附带反应
state    = apply(world.effects + reaction.effects)       # 每个变量每回合最多动一步
plan     = beats.plan_steps(beat, reaction)              # 主反应优先级 ≥ 8 时本回合不排步
if beat 在本回合结束（最后一步已排上，或用到 max_turns，或必接拍触发）:
    state.story_min += beat.minutes                      # 剧情时钟
    events = clock.crossed(old_min, new_min)             # Nora 事件
    next   = dm.decide(state)                            # 必接拍 → 直接接；否则优先级分层 → scorer
segments = narrator.write(input, reaction, plan, events, next.opening, knowledge_slice)
verdicts = guard.check(segments)                         # M3，不过就重写，最多 2 次
log(turn_record)
```

- **步指针由引擎推进，不由叙述者决定。** 引擎事先排好本回合要交代的步，叙述者回报的 `steps_delivered` 只用来核对；核对不上就重写一次，再不上也照常推进并记日志。这样 DM 才能在叙述之前就选好下一拍，把它的开场写进同一段文字（interaction-design.md §6.4）。
- **M4 不挡路。** 张力估计在段落发出之后异步计算，结果在下一次 DM 决策时才用到。
- **选项生成不挡路。** 玩家点了才调。

### 3.2 LLM 调用的统一处理

- **输出校验**：每个角色的输出都有一份 JSON Schema（`schemas/llm/`）。解析失败就带上错误信息重试一次，再失败就走兜底：叙述者用岔开话题的话，M2 判为合规并给空单元，M3 判为通过。每次兜底都记日志。
- **缓存**：键是 (角色, 模型, prompt 版本, system, user, 温度) 的 hash，存在 `data/cache/`。自博弈默认开，真人游玩默认关。
- **prompt 文件化**：`prompts/<role>_v<N>.md`，版本号写进每条日志。
- **离线 mock**：每个角色一个确定性的假实现，`LLM_PROVIDER_<ROLE>=mock` 时启用。
- **上线开关**（2026-10-06 定为保留）：某个角色配了真实供应商以后，还要列进 `LLM_LIVE_ROLES`，或者在 Console 里打开，才会真的调 API；否则仍然走它的离线 mock。这样测试和自博弈不会意外花钱。

### 3.3 角色与供应商（建议，对应待定项 B3）

| 角色 | 属于 | 要求 | 建议 |
|---|---|---|---|
| `review`（切分、翻译、合规、改写、分类） | M2 | 快、结构化输出稳 | 便宜快模型（如 DeepSeek） |
| `narrator` | 内容 | 文笔、遵守规则 | 质量更好的模型（如 Kimi） |
| `guard` | M3 | 快、判得准 | 便宜快模型 |
| `tension` | M4 | 稳定打分 | 便宜快模型 |
| `scorer`（B） | M1 | 结构化输出 | 便宜快模型 |
| `proposer` | 内容 | 推理 | 便宜快模型 |
| `options` | 内容 | 快 | 便宜快模型 |
| `selfplay` | 自博弈玩家 | 便宜 | 便宜模型 |
| `judge` | 离线标注 | 强，而且**和上面所有老师不是同一家** | 另一家强模型 |

---

## 4. 里程碑

建议的负责人按 backend-design.md §9 的分工：#1 M1 与 DM，#2 M2，#3 M3，#4 M4 与评估，#5 数据，#6 故事与前端。

### M0 · 骨架（10/7）

- [x] 建 `backend/`、`frontend/`、`schemas/`，按 §1 拷代码；`.gitignore` 加上 `.env`、`data/logs/`、`data/cache/`
- [x] `uv sync` 能装；`npm install && npm run dev` 能起
- [x] `engine/llm/client.py` 加缓存、prompt 版本、输出校验与重试（§3.2）
- [x] `.env.example` 列出每个角色的 `LLM_PROVIDER_<ROLE>` / `LLM_MODEL_<ROLE>` / `LLM_API_KEY_<ROLE>`

**验收**：`uv run pytest` 跑通拷过来的 DSL 测试；前端空页面能连上 WebSocket。

### M1 · 数据契约（10/7–10/8）

- [x] `schemas/state_v2.json`：story.md §8.2 的全部变量
- [x] `schemas/beat_v2.json`：步、`minutes`、`max_turns`、`entries`（各自的开场，取代 transition_in 的两个版本；邀请写在 entry 上）、`asks`、`on_silence`、`outcomes`、本地 `mix_in`（触发字段叫 `when`，不叫 `on`：PyYAML 会把裸的 `on:` 读成 True）、`must_follow`、`ending_rank`、`length`
- [x] `schemas/messages_v2.json`：interaction-design.md §11；跑 `gen:types` 生成前端类型
- [x] `schemas/llm/*.json`：每个 LLM 角色的输出格式
- [x] `data/clock.yaml`：各阶段默认 n、Nora 四级的分钟数、40 回合安全上限
- [x] `data/tension_curve.yaml`：按剧情分钟（story.md §6.2）
- [x] `data/interactions.yaml`：公寓的封闭动作表，包括房间移动（`go_to`）、物件动作、手机动作、`blocked_when`（interaction-design.md §6.6、§8），以及 beat-script.md §5 第 6 条的新动作：搜 Julian 的外套、看窗外、把手机递给别人、回短信
- [x] `data/knowledge/*.yaml`：每个人的知识卡，每条事实带解锁条件（story.md §5.4，按 T2）
- [x] `schemas/data/*.json`：上面四类数据文件各自的 schema；`backend/tests/test_contracts.py` 校验全部 schema、数据文件、DSL 能编译、文件之间一致
- [x] 状态里新增两个变量：`private_turns`（跟随规则用）、`police_called`（报警打通，结局判定按说了真话处理）

**验收**：所有 schema 和 YAML 都能加载并通过校验（测试覆盖）。

### M2 · beat 池 v0 和全局反应 v0（10/8–10/10）· 负责 #6

- [x] **20 个 beat**（`backend/data/beats/phase1/2/3.yaml`、`endings.yaml`）：
  - 主干 14 个：`the_door`、`dinner_on_the_crate`、`the_fourth_setting`、`mia_in_the_kitchen`、`julian_on_the_balcony`、`the_buzz`、`two_afternoons`、`noras_call`、`the_admission`、`the_versions`、`the_offer`、`downstairs`、`the_knock`、`testimony`；
  - 必接卫星拍 `dont_go_yet`；
  - 5 个结局。
- [x] **`data/reactions.yaml` v0**（校验用 `schemas/data/reactions.json`）：
  - 六个话题 × 三层的全局 mix-in；
  - 物件反应：箱子、合影、车、机票、外套、浴室门、TOOLS 箱、手机；
  - 行为模式：连续沉默、只跟一个人说话、反复提同一个话题；
  - 每人两条逼过头的反应；
  - 社交行为反应；
  - 每人一组岔开话题的说法；
  - 数值规则（interaction-design.md §5.4）。
- [ ] **写法**：先让 LLM 按 story.md 的意图起草 YAML，再人工逐条审。（起草完成，按 beat-script.md 转写；**人工审还没做**）
- [x] **golden path**：`tests/fixtures/golden_path.yaml`，由 `test_beat_pool.py` 用真实 DSL、effects 和时钟事件重放。用 scorer A 走一遍的 Baseline check 在 `test_session.py`（M3）
- [x] **测试**（`tests/test_beat_pool.py`）：
  - 无死局：随机走状态，任何可达状态下，要么有可选的 beat，要么有时钟事件可以快进（beat-script.md §5 第 3 条）；
  - 每个结局都有一条脚本化的路径能到；
  - 必接拍表（story.md §9.4）逐条触发；
  - 每个 beat 都声明了 `minutes`。

**验收**：beat 测试全绿（已达成）；DM 用 scorer A 能按 golden path 走完（M3 已达成）。

### M3 · 回合引擎（10/8–10/11，实际完成 10/12）· 负责 #1，#3 协助

- [x] `engine/clock/`：beat 结束时 +n，计算跨过的 Nora 事件，安全上限，空档快进；来电那一回合不选新拍
- [x] `engine/beats/`：v2 加载（按 `beat_v2.json` 校验）、步指针、`plan_steps`、`outcomes` 选择、`max_turns`；"中止"和"演过"分开记，中止的拍可以再选（`runner.py`）
- [x] `engine/state/` 和 `engine/dsl/`：初始状态改从 `state_v2.json` 的 `default` 生成；`story_phase` 按剧情分钟推导；去掉 beat 加载器里 `on:` 的兼容处理
- [x] `engine/dm/`：优先级分层、必接拍、结局表、目标弧按剧情分钟（每个候选按自己的 `minutes` 算目标斜率）、`GENERATE_NEW`（proposer 按 v2 生成，M1 排序）
- [x] `engine/world/`：执行动作单元，包括换房间（一次一间）、跟随、阻拦（被拦的人镇定值下降）、手机动作、`heard_by`
- [x] `engine/reactions/`：收集候选、按优先级选、确定谁来回应、只用一次、每变量每回合限一步、说法记录
- [x] `engine/narrator/`：组装 prompt（知识切片、反应指令、本回合的步、事件、下一拍开场、玩家原文），输出分段，核对 `steps_delivered`
- [x] `engine/input/`：整理（规则预检 + M2）、选项生成、`turn` 命名空间
- [x] `engine/models/`：四个统一接口（backend-design.md §7.2），各自的 rule / llm / trained(占位) 三路，影子模式
- [x] `app/session.py`：回合循环（§3.1）；整理、提交、选项三个入口；控制命令：强制换拍、改状态、调时钟、换 scorer、注入一回合
- [x] `engine/journal/`：回合日志（interaction-design.md §13）、决策日志、会话汇总
- [x] `tools/play_cli.py`：在终端里玩，支持 `/channels`、`/options`、`/phone`、`/state`、`/trace`

**验收（里程碑 A）**：离线 mock 下，用 `play_cli.py` 在终端里从开局玩到结局；`test_session` 用脚本输入跑完整局（已达成：`tests/test_session.py`、`tests/test_play_cli.py`；60 局随机脚本玩家全部走到结局，四种结局都出现）。

实现时定下的细化（2026-10-12）：

| # | 细化 | 理由 |
|---|---|---|
| R1 | 主反应打断步只看**类型**：只有"逼过头"让本回合不排步。§3.1 写的"优先级 ≥ 8"会让每条本地 mix-in（10）和每次动作受阻（9）都卡住 beat | mix-in 和受阻本来就是顺带回应，回应完接着演 |
| R2 | 本地 mix-in 当主反应时不配附带反应；岔开话题永远不当附带反应 | 同一件事不演两遍；岔开只会添噪音 |
| R3 | 提问的步在最后一个允许的回合抛出时，回答那一回合不算进 `max_turns` | 否则问题抛出后没有机会回答 |
| R4 | 结局拍在选中的那一段里整拍演完（开场、全部步、尾声） | 结局不需要玩家再输入 |
| R5 | 生成拍的收敛规则改成"连续生成两拍后 `GENERATE_NEW` 退出候选"，不强制生成结局 | 时钟事件一直在，第 16 分钟必接 `the_knock`，不会卡死 |
| R6 | M3 两次重写都不过时，只替换出问题的分段（NPC 台词换成岔开、旁白换成中性句、玩家分段按原文重写），不整段替换 | 整段替换会丢掉玩家的言行和本回合的步 |
| R7 | 每个 LLM 角色没有 prompt 文件时用内置的 v0 短 prompt（`engine/models/prompts.py`），M4 的 `<role>_v1.md` 落地后自动接管 | 让 llm 路径在 M4 之前就能接真供应商 |
| R8 | 离线 mock 的 review / guard / tension 直接用各自的 rule 路径作答 | 一份规则实现同时当 baseline 和离线 mock |

### M4 · LLM mock 接入（10/10–10/13，实际完成 10/12）· 负责 #2、#3、#4、#1 各管自己的模块

- [x] 写 prompt v1：`review`、`narrator`、`guard`、`tension`、`scorer`、`proposer`、`options`、`selfplay`、`judge`（`backend/prompts/<role>_v1.md`；review 的动作表由 `interactions.yaml` 生成后填进 `{{ACTION_TABLE}}`）
- [x] 每个模块一套小评测集 `prompts/evals/<role>.jsonl`：review 35 条（九类违规各 2 条、合规 10 条、切分翻译和 Nora 7 条）、guard 20 条（四类各 5 条）、tension 10 个窗口、scorer 10 个决策点
- [x] `tools/eval_prompts.py`：一条命令跑完所有评测集，llm 路径和 rule 基线并排输出；`--offline` 走离线 mock
- [x] 按 §3.3 配好供应商（DeepSeek：review / guard / tension / scorer / options / proposer；Kimi：narrator / selfplay / judge），用 `LLM_LIVE_ROLES` 或 `play_cli.py --live all` 打开
- [x] 各阶段延迟写进日志；每个 LLM 调用的角色、模型、prompt 版本、延迟和重试次数记进回合日志的 `llm_calls`，`play_cli.py /trace` 能看到

**验收（里程碑 B）**：真实 LLM 下用 `play_cli.py` 玩完一局（记录在 `prompts/evals/results/live_playthrough.txt`）；评测集结果入库（`prompts/evals/results/`），作为 prompt 的回归基线。

基线（2026-10-12，prompt v1）：

| 模块 | 模型 | llm 路径 | rule 基线 |
|---|---|---|---|
| review（M2） | deepseek-flash | 合规判断 100%，误拒 0%，漏拦 0%；对谁、话语行为、动作、翻译、Nora 判定全对 | 89%，误拒 6%，漏拦 17%，不会翻译 |
| guard（M3） | deepseek-flash | 95%（21 条，跑 3 次都是 95%）；误拦 0–20%（3 次里有 1 次误拦了 1 条正常旁白）；矛盾 6/6 | 52%，抓不到矛盾 |
| tension（M4） | deepseek-flash | MAE 0.25–0.30，Spearman 0.98 | （无：rule 读的是 beat 自报的值） |
| scorer（M1） | deepseek-flash | top-1 100% | top-1 80% |

真实 LLM 整局（2026-10-12，`live_playthrough.txt`）：脚本玩家走 golden path，42 回合到 `confession` 结局，剧情时间 18.5 分钟，15 个主干拍全部演完，没有兜底、没有修补，guard 打回重写 4 次。**每回合平均约 50 秒，远超 §6 估计的 6–10 秒**：

| 角色 | 模型 | 调用 | 平均延迟 |
|---|---|---|---|
| narrator | kimi-k3 | 46 | 49.5 秒 |
| guard | deepseek-flash | 46 | 24.5 秒（含一次 615 秒的挂起） |
| scorer | deepseek-flash | 8 | 13.5 秒 |
| review | deepseek-flash | 42 | 4.9 秒 |

同一个请求单独测叙述者：kimi-k3 22–44 秒，kimi-k2.6 75–156 秒，deepseek-v4-pro 33–41 秒，**deepseek-flash 7–9 秒，文笔相当**。叙述者换哪个模型待定（P2）。

实现时定下的细化：

| # | 细化 | 理由 |
|---|---|---|
| R9 | 供应商报错（4xx、5xx、超时）和输出不合格一样：重试一次，再走兜底，不让一次报错中断回合 | 真实供应商偶尔返回空内容或 503 |
| R10 | 每个角色的输出上限放大到 4000–8000 token | 推理型模型先消耗推理 token，上限小时会返回空内容或被截断的 JSON；只按实际产出计费 |
| R11 | JSON 模式下用户消息里没有 "json" 时自动补一句 | DeepSeek 要求用户消息里出现这个词才接受 JSON 模式 |
| R12 | tension 的 llm 路径只读文本窗口，不再把 beat 自报的张力放进 prompt | backend-design.md §2 原则 5：不能用 beat 自报的数值来评估 DM |
| R13 | guard 的输入加上场景信息（房间、在场的人、各人位置、木箱和手机状态、`heard_by`） | 判断"对没听到的话作出反应"这一类矛盾需要它 |
| R14 | 每个角色设请求超时（默认 60 秒，narrator 90 秒，proposer 和 judge 120 秒，`LLM_TIMEOUT_<ROLE>` 可改），关掉 SDK 自带的重试 | SDK 默认等 600 秒再静默重试，曾让一个回合卡了 13 分钟 |
| R15 | narrator 和 guard 的 prompt 写明固定设定（去澳大利亚、6 点搬家、07:40 的航班、人物关系），改动设定按矛盾处理 | 试玩中叙述者 7 次把目的地写成 Lisbon，guard 没拦 |

Sonnet 玩家试玩（2026-10-12，`sonnet_playthrough.md`）之后定下的改动（2026-10-13）：

| # | 改动 | 理由 |
|---|---|---|
| R16 | 叙述者兜底链：主模型 45 秒超时；超时或报错就换下一个模型（`LLM_FALLBACK_NARRATOR`，借用其他角色的端点），都失败才用拼接文本；每回合叙述总时长有上限，重写时预算用完就保留上一稿并修补 | 7 个回合两次超时，5 次把原始舞台说明和条件文字漏给玩家 |
| R17 | 报警分"明说"和"暗中"：打电话一律算明说，Julian 在场（Nora 不在）就拦，拦法看镇定值；给 911 发短信算暗中，Julian 镇定值 ≥ 0.6 不起疑，0.3–0.6 问"你在给谁发消息"（下一回合撒谎就发出去，说实话或沉默就被拦），< 0.3 直接拦；威胁过他之后至少会问；被拦过一次再坚持就能打通 | 原规则下 Julian 镇定值低于 0.3 就拦不住，中段以后报警永远打得通 |
| R18 | 新状态 `threatened_julian`（累积）：当着 Julian 的面说要说出去，或报警被他拦下，就记为 true；`second_crate` 改用它，不再要求威胁发生在当回合 | 第二只箱子的窗口只有 3 回合，还要碰巧在其中一回合说出威胁 |
| R19 | `open_it` 新增入口：报警打通时 Mia 已到自首边缘（镇定值 < 0.15，站在她这边），她在开箱前主动承认 | 报警打断了自首，但玩家把她带到边缘这件事要体现在结局里 |
| R20 | 给 Leo 打电话时 Julian 在场，响的是他的外套口袋 | 原来只写"附近有什么在震"，在他身边打也一样 |
| R21 | 叙述者请求加上剧情台账（各人位置、本回合的位置变化、已发生的事、谁听到了什么）和已说过的 NPC 台词，要求不重复原话 | 叙述者只看到最近两段，"谁给你发消息"之类的台词反复出现；beat 结束时把人移回客厅，正文却没写 |
| R22 | "带着某人走"：`go_to` 的动作原文里带上了在场的主人（牵着、带着、拉着），按 `take_aside` 结算，两人一起移动 | 第 30 回合牵着 Mia 去门厅，Mia 留在了客厅 |
| R23 | 站队问题由 review 直接判断这句回答站在哪一边（`side_answer`），规则只在它缺席时兜底 | 第 17 回合"我会对 Mia 好，但我不会答应你"被判成站 Julian |
| R24 | 玩家卡：开局推送 `player_card`（player.yaml 中玩家开局就知道的条目加人物关系），终端 `/card` 随时再看 | 真人玩家开局不知道 Leo 是谁、Nora 是谁 |

| R25 | 镇定值校准：每回合最多动 0.1（原 0.2）；说法和证据只在对方第一次听到时扣分（`turn.fresh`）；没被动摇的回合回升 0.05，Julian 最多回到 0.6、Mia 0.5，Leo 的死说破后不再回升 | 两局里 Mia 第 7–10 回合、Julian 第 8–19 回合就降到 0 并贴底，此后玩家的施压和安抚都不再改变数值，R17 的察觉分档也失去意义。用两局的真实输入重放：校准后中段在 0.3–0.6 之间随玩法起伏，Sonnet 局仍然走到 `confession`，一直重复同样说法的脚本局改走 `open_it` |

| R26 | beat 步骤的分支改成结构化的 `lines`：每行带 `when`，引擎在交付这一步时按当时的状态挑出成立的行，接在 `do` 后面交给叙述者；结局的步骤在结局效果生效之前求值。7 处 "If… / Or… / Unless… / Left early:" 全部改写，测试检查以后不再有人把条件写进正文 | 叙述者拿不到 `couple_unity`、`side`、镇定值，正常返回时只能猜分支，超时兜底时把所有分支原样漏给玩家（Sonnet 局第 32 回合） |

暂不处理：提前崩溃（镇定值见底时直接进结局）。

### M5 · 前端（10/11–10/16）· 负责 #6

- [x] Play 界面（interaction-design.md §10，2026-10-16 完成第一版，离线 mock 下用 Chrome 走通了开局、草稿、被拒、选项、地图、手机、桌面和移动端）：
  - 开局页（名字、性别）、正文记录（分段拼成文字，上面一行玩家原文）；
  - 输入区：单框和分栏切换，草稿确认（含翻译），被拒提示和一键改写；
  - 生成选项按钮、手机抽屉、房间和在场人物条、插图占位、"生成中"状态、结束页。
- [x] Console（2026-10-16 第一版）：会话选择、回合检查器（每回合完整链路）、状态、按剧情分钟的张力曲线（目标、beat 自报、M4 实测，附表格视图）、决策记录、拍子架、控制面板（scorer、tau、指定下一拍、跳时钟、状态补丁、重置、各 LLM 角色切换 live）。一个会话可以同时被玩家页和 Console 连接，`GET /api/sessions` 列出全部会话
- [x] 后端配套：`GET /api/intro`、`/art` 静态资源、`passage.illustration`（`data/tableaux.yaml`）、结局后才开放的 `GET /api/sessions/{id}/truth`（`data/truth.yaml`）；`?mode=play` 的连接收不到 `drama_state` 和 `turn_trace`
- [ ] 前端不理解剧情：只显示后端给的内容，只上报玩家输入（沿用 Wrongest Person 的规矩）

**验收**：浏览器里玩到结局；Console 能逐回合看到完整链路。

### M6 · 自博弈（10/13–10/16）· 负责 #5

- [ ] 按 [selfplay.md](selfplay.md) 实现（2026-10-26 取代原来的 5 种人格；玩家性格生成器已完成，见 selfplay.md §9）：HEXACO 六维抽样推导行为轴、每局目标、玩家模型按局轮换、DM 策略混合；一部分回合写单框原文、一部分给分栏；按违规率故意写违规输入
- [ ] 批量运行：并发数、预算上限（局数、token、金额），中断后可以续跑
- [ ] `claude_cli` 和 `codex_cli` 供应商（selfplay.md §2、§9）：订阅模型只用于测试局玩家和 judge 交叉检查
- [ ] `tools/selfplay_report.py` 输出统计：
  - beat 覆盖率、每局回合数和拍数、结局分布；
  - 被拒率、M3 重写率和兜底率；
  - 各阶段延迟、每局成本。

**验收**：50 局不崩；至少 4 种结局出现过；统计报告入库。

### M7 · 跑通验收与数据导出（10/17–10/18）· 负责 #5，全员

- [ ] `tools/export_datasets.py`：从日志导出数据集 v0（backend-design.md §5.2 的五个子集），附带 `data_version` 和 `schema_version`
- [ ] 小批量跑一次离线 judge 预标注（pairwise），检查格式
- [ ] 按 §0.2 逐条验收，写一页验收记录（数字和截图）

**验收（里程碑 C，10/18）**：§0.2 全部打勾。

### 并行：beat 池补全（10/12–10/18）· 负责 #6

- [ ] 剩下的约 15 个卫星拍，用同样的"LLM 起草 + 人审"流程补完
- [ ] 从中挑出留出 beat 测试集的 3 个（backend-design.md §5.3）

---

## 5. 依赖与关键路径

```
M0 ─► M1 ─┬─► M2（beat 池 v0）──┐
          └─► M3（回合引擎）────┴─► 里程碑 A ─► M4 ─► 里程碑 B ─┬─► M5（前端）───┬─► M7 ─► 里程碑 C
                                                              └─► M6（自博弈）─┘
                                    beat 池补全（并行，不卡验收）
```

- 关键路径是 M1 → M3 → M4 → M6：自博弈产数据，数据是整个课设的关键路径（backend-design.md §10）。
- 前端不在关键路径上。里程碑 A 之前，前端只需要搭好脚手架和协议类型。

---

## 6. 风险

| 风险 | 对策 |
|---|---|
| 每回合 6–10 秒太慢 | 记录各阶段延迟；整理结果复用；M4 和选项异步；M2 和 M3 用快模型 |
| LLM 输出的 JSON 不合格 | 输出校验、重试一次、兜底，每次兜底都记日志（§3.2） |
| 叙述者替玩家写东西或说漏秘密 | 知识切片 + M3；评测集里专门放这两类 |
| beat 池写不完 | 先 20 个跑通；其余用 LLM 起草、人审，和验收并行 |
| 自博弈成本超支 | 便宜模型、缓存、批量运行带预算上限 |
| API key 泄漏 | key 只放 `.env`，不入库；不拷 Wrongest Person 的 `llm_providers.env` |
| 玩家名字等个人信息进入 LLM | 真人游玩一律用化名（backend-design.md §5.5） |

---

## 7. 开工前要定的

| # | 问题 | 本计划的默认 |
|---|---|---|
| P1 | 代码放在哪（backend-design.md B1） | Fragile 仓库，Wrongest Person 只读 |
| P2 | 每个角色用哪家 LLM（backend-design.md B3） | §3.3 的建议 |
| P3 | 每个里程碑由谁负责 | §4 按 backend-design.md §9 的分工 |
| P4 | 步指针由引擎推进、叙述者只回报核对（§3.1），这是对 interaction-design.md §6.2 的细化 | 采用 |
