# Fragile：后端与学习模块设计（DL 课设版）

> v0.2 · 2026-10-06（按 interaction-design.md 改成回合制）
> 课程：CSCI 566 Deep Learning and Its Applications（Fall 2026）· 课程项目 · 6 人组
> 配套：[story.md](story.md)（剧情设定）、[interaction-design.md](interaction-design.md)（交互设计：回合流程、输入合规、反应层、叙述者）
> 继承：Wrongest Person 后端（`D:\OtherProjects\WrongestPerson\backend`，设计见该仓库的 `docs/backend-design.md`）。
> 本文只写变化和新增的部分。没提到的（规则 DSL、beat schema、DM 决策循环、日志格式、`/author` 工作流）一律沿用。

---

## 0. 一句话

LLM 当老师和数据工厂；运行时的四个关键判断，由四个我们自己训练的小模型来做：

- **M1** 选下一个 beat
- **M2** 理解玩家，并判断输入是否合规
- **M3** 守住秘密
- **M4** 测量张力

---

## 1. 课程要求与本设计的对应

### 1.1 评分环节

| 课程要求 | 时间 | 本设计里对应的部分 |
|---|---|---|
| Pre-proposal（组员、想法、数据集） | 10/5，已交，但没写数据集 | 数据集 Fragile-DM 在中期报告里第一次正式提出（§5），建议先在 office hour 跟老师确认自建数据集可以接受 |
| 中期报告（进展、文献综述、初步结果） | 11/9 | 数据集 v1 的统计、M1/M2 的初步结果（§10） |
| 最终报告（动机、方法、实验、结果） | 期末 | 四个研究问题加消融实验（§6） |
| Poster | 11/30 | Console 截图、曲线、现场演示（§7.4） |
| 组内匿名互评 | 期末 | 每人负责一个可度量的交付物（§9） |

### 1.2 课程内容

| 课程主题 | 在本项目里的位置 |
|---|---|
| 神经网络、反向传播、训练动态 | 四个模块的训练；loss 曲线和校准曲线进报告 |
| RNN 与 LSTM | M4 的 GRU 版本 |
| 迁移学习 | M1 的 LoRA 微调；M2 在 SwDA/DailyDialog 上预训练；M3 走 MNLI → DialogueNLI → 本项目数据的三段迁移 |
| 注意力、解码 | 四个模块都用 transformer；DM 的温度采样 τ |
| 自监督学习与 LLM | LLM 当老师（蒸馏）、LLM-as-judge |
| OOD 与异常检测 | M2 的 OOD 分决定要不要生成新 beat；M3 检测泄密和矛盾 |
| Scaling laws | M1 的数据量缩放曲线 |
| 强化学习 | M1 是 RLHF 里奖励模型那一环；整局级 offline RL 是延伸目标（§4.5） |
| 生成模型 | 插图一致性 LoRA（可选的 M5，§4.5） |

---

## 2. 设计原则

1. **决策归训练出来的模型，内容归 LLM。** 运行时决策路径上的每个判断都由我们拿着权重的模型做。API LLM 只负责两件事：生成内容（叙述段落、新 beat、选项、翻译、改写、插图）和离线打标签。
2. **每个模块三路可切换**：`rule`（规则或启发式 baseline）、`llm`（零样本 LLM，就是老师）、`trained`（学生）。接口沿用 Wrongest Person 的 scorer A/B/C。每个模块天然带 baseline，每个模块都能出一张结果表。
3. **影子模式。** 自博弈和数据采集时，三路实现每次都算、都记日志，但只用其中一个做决定。用户研究时只跑被测的那一路，省钱，也避免泄题。
4. **训练标签可以来自 LLM，测试集只能人工标。** judge 不能既当训练老师又当最终裁判。
5. **张力用 M4 测，不用 beat 自己声明的 effects 来评估。** 否则"按声明的 effects 选 beat，再按声明的 effects 打分"就是自己考自己。
6. **模型要小。** 都要能在 Kaggle 免费 GPU 上训练。M2、M3、M4 能在 CPU 上推理；M1 在 CPU 上也能放进 beat 边界 2 到 4 秒的决策预算里。

---

## 3. 架构

### 3.1 在线：一回合

回合制，生成时玩家不能输入，没有打断。完整说明见 interaction-design.md §2。

```
发送前（不消耗回合）
玩家输入（单框 / 分栏 / 选项）
   │
   ▼
[M2 输入编码器] ── 切分 · 合规 · 单元列表（话语行为 · 对谁 · 话题 · 动作）· 怀疑度 · claims · OOD 分
   │                （翻译和改写由 LLM 做）
   ├─ 不合规 ─► 系统说明 + 一键改写 ─► 玩家重写
   ▼
发送后
世界规则：动作尝试 → 结果（NPC 阻拦、换房间、跟随）
   │
反应层（规则表）：主反应 + 附带反应 + 数值变化
   │
beat 推进一步 ── 本拍结束时：
   │    ├─ 有必接拍 ─► 直接接上，不经过打分器
   │    └─ 否则候选 = 最高优先级层的 beat + GENERATE_NEW
   │         ├─ M2 的 OOD 分 > θ，或 GENERATE_NEW 得分最高 ─► proposer LLM 生成 1 到 3 个 beat
   │         │                                               ─► 硬检查 ─► [M1] 选最好的
   │         └─ 否则 ─► [M1 奖励模型] 给候选打分 ─► 按温度 τ 采样
   │
本拍结束时剧情时钟 +n · 跨过的 Nora 事件
   │
叙述者 LLM 写第一人称分段 ─► [M3 一致性守卫] ─┬─ 通过 ─► 输出给玩家
                                              └─ 泄密 / 矛盾 / 替玩家写 ─► 带提示重写（最多 2 次）

[M4 张力估计器]：beat 边界从最近几回合测出 tension_measured
插图服务（异步）：beat 里标记的 tableau 时刻 ─► 取缓存或现场生图
选项（玩家点了才生成）─► [M3] ─► 输出给玩家
```

### 3.2 离线：训练回路

```
自博弈（人格 × 探索策略）+ 真人游玩
   ─► 日志（决策、话语、台词、状态，每条都带各模块输出和模型版本）
   ─► 标注任务：judge 预标注 ─► 人工标注（Console 的 Annotate）
   ─► 数据集 Fragile-DM vN（按局切分，带 schema_version 和 data_version）
   ─► 训练（Kaggle / Azure）─► 模型注册表（权重、model card、metrics.json）
   ─► 热替换回后端 ─► 评估套件自动出报告用的表格和曲线 ─► 下一轮自博弈（on-policy 数据）
```

### 3.3 和 Wrongest Person 后端的差异

| 处理 | 部分 |
|---|---|
| **沿用** | 规则 DSL → JSON Logic、beat YAML 与热加载、`BeatPool`、DM 决策与采样、`GENERATE_NEW` 的 proposer + 硬检查 + 收敛规则、JSONL 日志、自博弈框架、LLM 按角色切换供应商、Console 的 Decision Log / Annotate |
| **修改** | 状态 schema 换成 `state_v2`（见 story.md §8.2）；会话循环从"等待 + 超时 + 每拍交换上限"换成回合循环；时钟换成剧情时钟（每过一个 beat +n，n 由 beat 声明，proposer 生成的 beat 也要声明）；beat 的 goals 换成"步"（interaction-design.md §6）；DM 选拍前先做优先级分层，必接拍不经过打分器；scorer 接口推广成四个模块的统一接口；performer 换成叙述者，输出第一人称分段，不再输出立绘命令和话语行为（改由 M2 负责）；判断"货架不够用"加入 M2 的 OOD 分 |
| **新增** | M1 到 M4 的 trained 实现；`ml/` 包（数据、训练、评估、注册表）；模型推理服务；反应层（`engine/reactions/` 和 `data/reactions.yaml`）；整理（切分、翻译、合规、改写）和选项生成两个 LLM 角色；NPC 阻拦、换房间、跟随的世界规则；插图服务；新的标注界面；Console 的回合检查器 |
| **删除** | 打断拍和 `repeatable` 中间态；等待超时；TTS 和 ElevenLabs、字符级对齐、立绘与 Sprite 命令通道、地图与 `near()`（换成房间枚举） |

---

## 4. 四个可训练模块

### 4.1 M1 · Beat 奖励模型（核心）

| 项 | 内容 |
|---|---|
| 任务 | 给定当前状态和最近几回合，判断哪个候选 beat 更好 |
| 运行时位置 | beat 边界给候选打分：先做优先级分层，只给最高那一层的候选打分，必接拍不经过 M1；`GENERATE_NEW` 时给 proposer 的 1 到 3 个草稿重排，在运行时替代 judge（judge 只留在离线） |
| 输入 | [annotation.md](annotation.md) §4 标注包的第 1 到 3 层（局面卡、确定性生成的前情台账、当前 beat 内至少 3 回合原文）加 `textualize(beat)`（开场句、意图和各步），约 800 到 1500 token。人工标注者和 judge 看的是同一份内容。不用 LLM 摘要；scorer 永远不看 beat id |
| 输出 | 标量 reward |
| 模型 | 0.5B 级开源基座（主实验）和 1.5B 级（消融，用 QLoRA），加 LoRA（r = 8 或 16）和最后一个 token 上的线性 head |
| 损失 | Bradley–Terry：`−log σ(r(s, b₊) − r(s, b₋))` |
| 数据 | 偏好对子集（§5） |
| 三路实现 | `rule` 是 A（Façade 公式）；`llm` 是 B（零样本 offset）；`trained` 是 C-LoRA。另加 C-MLP（手工特征）作对照 |
| 指标 | 人工测试集上的 pairwise 准确率；Baseline check 的 top-1 命中率；用 M4 测出的张力和目标弧之间的误差；每次决策的延迟 |
| 消融 | 只看状态 vs 状态加对话；基座 0.5B vs 1.5B；数据量缩放曲线（10%、25%、50%、100%）；只用 judge 标签 vs judge 加人工；LoRA rank；C-MLP vs C-LoRA；**留出 beat 泛化**：训练时没见过的 beat 上的 pairwise 准确率和 top-1 命中率，和见过的 beat 对比（切分见 §5.3） |

输入模板示例：

```
[STATE] phase=mid; tension_measured=3.1; side=+1 (leans Mia); couple_unity=2;
        nora_pressure=2; revealed={car_downstairs, missed_call}; crate=sealed; player_room=kitchen
[DIALOGUE] Mia: "Leo was always... is always late." | You: "When did you last talk to him?"
[CANDIDATE] type=satellite; slope=+1; intent: Julian steers attention to Mia and Leo's
            closeness, to pull the player away from Mia.
```

### 4.2 M2 · 玩家输入编码器（多任务）

| 项 | 内容 |
|---|---|
| 任务 | 把玩家一回合的输入变成结构化信号，并判断输入是否合规 |
| 输入 | 玩家一回合的输入（单框原文，或者台词 / 动作 / 神态三栏），加上前两段 NPC 台词、当前房间和在场的人 |
| 输出 1 | **切分**：把单框原文切成台词、动作、神态三栏，token 级序列标注；分栏输入跳过这一步 |
| 输出 2 | **单元列表**。每个单元带：渠道；**话语行为**，单标签，27 类：15 个通用（agree / disagree / ask / explain / praise / criticize / comfort / provoke / confide / joke / refuse / thank / apologize / greet / leave），10 个本故事专属（ask_about_leo / ask_about_crate / ask_about_afternoon / ask_about_move / mention_car / mention_voicemail / accuse_julian / accuse_mia / threaten_to_tell / promise_silence），再加 silence 和 observe；**对谁**：julian / mia / both / self / nora；**话题**，多标签：crate / leo / money / afternoon / marriage / college；**动作解析**：映射成封闭动作表里的 (verb, target)，或者判为 `implausible`，动作表来自新的 `interactions.yaml` |
| 输出 3 | **怀疑度**：整回合，回归 0 到 3，写进 `player_suspicion` |
| 输出 4 | **claims**：整回合，多标签，按 `revealed` 的事实词表标出玩家在台词里声称知道的事实 |
| 输出 5 | **合规**：整回合，10 类，ok 加九类违规（npc_action / npc_speech / outcome / perception / invention / stride / absurd / out_of_scope / meta），定义见 interaction-design.md §4.2；外加违规片段 |
| 输出 6 | **OOD 分**：这一刻是不是落在货架 beat 覆盖不到的地方 |
| 不归 M2 | 翻译和一键改写是生成内容，一直由 LLM 做 |
| 模型 | DeBERTa-v3-base 共享 encoder：切分用 token 分类头，单元级和整回合级各几个 head；OOD 在 encoder 的 embedding 上算 |
| 训练 | 先用 SwDA / DailyDialog 预训练话语行为头，再用老师 LLM 的标签多任务微调（蒸馏）。切分和对谁另有玩家确认过的数据（interaction-design.md §12）；合规头另加扰动样本：把合规的输入改写成每一类违规 |
| OOD 方法 | 在"被作者 beat 妥善接住"的时刻的 embedding 上拟合分布，比较 Mahalanobis、kNN 和 energy score（来自话语行为头的 logits），用 PyOD 实现 |
| 三路实现 | `rule`：关键词规则，按引号和星号切分；`llm`：老师 LLM，mock 阶段一次调用给出切分、翻译、合规、改写和分类；`trained`：本模型 |
| 指标 | 各头对人工标注集的 macro-F1、MAE；切分的 token F1；合规头的**误拒率**和漏拦率；学生对老师的一致率；CPU 延迟；每局成本。OOD 用 AUROC（人工标注"这里该生成新 beat"的时刻） |
| 消融 | 有无 SwDA 预训练；单任务 vs 多任务；上下文窗口长度；三种 OOD 方法；"OOD 触发"vs"GENERATE_NEW 当伪候选打分"；合规头有无扰动样本 |

### 4.3 M3 · 一致性守卫

| 项 | 内容 |
|---|---|
| 任务 | 叙述者写的这一段，有没有提前说出秘密、和事实矛盾，或者替玩家多写了东西 |
| 输入 | 叙述者分段里的一段，以及它的类型（interaction-design.md §9.1）。按类型对照不同的东西：NPC 台词对照说话人的知识卡（story.md §5.4 里说话人那一列）；旁白对照玩家知识卡和当前可感知的东西；玩家的动作和台词对照玩家原文。另外都带上当前 `revealed`、已解锁的话题层级和 `heard_by` |
| 输出 | 四类：consistent / premature_leak / contradiction / player_overreach，外加涉及哪个事实或哪一段 |
| 模型 | DeBERTa-v3-base 的 NLI 式 cross-encoder |
| 训练 | 三段迁移：MNLI → DialogueNLI → Fragile-DM 的段落子集 |
| 数据 | ① 叙述者的自然输出，由 judge 标注；② 受控扰动：让 LLM 把一段一致的文字改写成"泄露事实 X""和事实 Y 矛盾""替玩家多写一个动作或内心"的版本，作困难负样本；③ 人工测试集约 600 段 |
| 运行时 | 在叙述者之后、显示给玩家之前逐段检查；选项也要检查。被判有问题时，带提示重写，最多 2 次；还不过，就换成一句岔开话题的台词加一句中性旁白。每次判定都写日志 |
| 三路实现 | `rule`：在段落里匹配未解锁事实的关键词，玩家段落和原文比对新增的动词；`llm`：judge 当守卫；`trained`：本模型 |
| 指标 | 检测的 AUROC 和 F1；守卫关 / LLM 守卫 / 训练守卫三种情况下，每局的泄密率、矛盾率和替玩家写的比例；**误拦率**（拦太多会把戏拦死）；延迟 |
| 消融 | 三段迁移各去掉一段；有无困难负样本；有无知识卡输入 |

推理悬疑最怕 NPC 说漏嘴，第一人称叙述又最容易替玩家做决定，所以这个模块是故事本身需要的，不是为了凑 DL。它也落在课程"异常检测"那一讲和老师实验室做的 agent 可信度方向上。

### 4.4 M4 · 张力估计器

| 项 | 内容 |
|---|---|
| 任务 | 从最近 N 回合测出此刻的戏剧张力 |
| 输入 | 最近 N 回合的玩家输入和叙述段落，带说话人标记（N 是消融项），可选再加文本化的状态 |
| 输出 | 0 到 5 的张力值，写进 `tension_measured` |
| 模型 A | GRU：每轮话先用冻结的 MiniLM 编成句向量，再在句向量序列上跑 GRU |
| 模型 B | DeBERTa-v3 encoder：整个窗口拼起来一次读完 |
| 损失 | MSE，另试一个有序分类版本（5 类有序 logits） |
| 标签 | judge 给窗口打分；人工标 300 个窗口，每个 3 人标，用 Krippendorff α 衡量人与人之间的一致度，作为上限 |
| 用途 | ① **评估**：弧误差用测出来的张力算，不用 beat 自报的 effects；目标弧的横轴是剧情分钟（story.md §6.2）；② **运行时**：`tension_measured` 进入 M1 的输入（有无它是一项消融） |
| 三路实现 | `rule`：累加已播 beat 的 effects（也就是现在的做法）；`llm`：judge 现场打分；`trained`：本模型 |
| 指标 | 对人工标签的 Spearman ρ 和 MAE；和人与人一致度的差距 |

### 4.5 可选模块（人手富余时做）

- **M5 · 插图一致性**：用定稿的角色设定图给扩散模型训 LoRA，用 CLIP / DINO 的身份相似度衡量同一角色在不同插图里像不像。对应生成模型那一讲，海报效果最好。
- **M6 · 整局级 offline RL**：用整局评分（judge 加问卷）学 Q(state, beat)，和 M1 的逐步奖励比较。对应强化学习那一讲。

---

## 5. 数据集：Fragile-DM

### 5.1 生产流水线

> 2026-10-26：自博弈的具体方案改由 [selfplay.md](selfplay.md) 定义：玩家性格按 HEXACO 六维抽样再推导行为轴，玩家模型按局轮换，叙述者固定 deepseek-flash，judge 固定 kimi-k3。下面的"5 种玩家人格"保留为原始设想。

- **自博弈的变化维度**：
  - 5 种玩家人格：礼貌的客人、追问的侦探、挑事的人、站某一边的人、想走的人；
  - 玩家名字和性别随机；
  - 探索策略：约 20% 的局用随机 scorer 或高温 τ，保证偏好数据里有足够多的"非最优"候选，不只是当前策略会选的那些；
  - 输入方式：自博弈玩家一部分回合写单框原文（练切分），一部分直接给分栏；约 10% 的回合故意写违规输入，覆盖九类违规（练合规头）。
- **真人游玩**：组员和同学，在用户研究之外另算。
- **自博弈不依赖前端**，后端进程内直接跑，沿用 `selfplay/run.py`。
- **成本控制**：自博弈的叙述者和玩家用便宜模型；judge 用强模型，但只用来打标签；所有 LLM 调用按 prompt 的 hash 缓存。

### 5.2 子集与规模目标

| 子集 | 单位 | 训练标签 | 人工测试集 | 目标规模 | 给谁 |
|---|---|---|---|---|---|
| 偏好对 | (状态, beat_A, beat_B) | judge 偏好加理由 | 500 对 | 自博弈约 600 局 × 约 15 次决策；judge 对约 3 万对 | M1 |
| 玩家输入 | 一回合输入加上下文 | 老师 LLM 的多头标签（含切分和合规）；真人玩家确认过的切分和对谁 | 1000 条 | 约 1 万条 | M2 |
| 合规扰动 | 合规输入改写成的违规版本 | 扰动自带标签 | 并入上面的 1000 条 | 约 3000 条 | M2 |
| OOD 时刻 | 一个决策点 | 无（只从"被接住"的分布学） | 300 个"该不该生成"的判断 | 来自决策日志 | M2 |
| 叙述段落 | 一段加知识卡和玩家原文 | judge 的四分类；扰动样本自带标签 | 600 段 | 约 1.5 万自然段，加约 6000 扰动段 | M3 |
| 张力窗口 | N 回合 | judge 的 0 到 5 分 | 300 个窗口 × 3 人 | 约 8000 个 | M4 |

规模都是目标，中期报告按实际跑出来的数报。

**人工标注预算调整（2026-10-26）**：人工标注总共只有约 250 条判断，上表的"人工测试集"一列改按 [annotation.md](annotation.md) 执行：M1 的 judge 校准集 40 条、测试集 100 条（加复标 20 条），M4 张力窗口 20 个 × 2 人，M2 和 M3 不新增人工标注。

### 5.3 切分规则

- **按局切分**：同一局的数据只能出现在一个 split 里，防止泄漏。
- **人工测试集**永远不参与训练，也不用来调 prompt。
- **留出 beat 测试集**（给 M1）：
  - 从卫星拍里留出约 20%（15 个里留 3 个），按阶段和斜率正负分层挑选。主干拍、必接拍和结局不留出：必接拍本来就不经过打分器，主干拍和结局几乎每局都会出现。
  - 留出的 beat 照常在自博弈和游玩里出现，只是数据切分时：任何一个候选是留出 beat 的偏好对，都不进训练，单独组成留出测试集。
  - 这项实验检验 §4.1 的约束：scorer 只看 beat 的内容，不认 beat id，所以对没见过的 beat 也应该能打分。
  - proposer 现场生成的 beat 天然是没见过的，`GENERATE_NEW` 重排时的表现也一并报告。

### 5.4 外部数据（迁移学习）

| 数据集 | 用途 |
|---|---|
| SwDA（Switchboard Dialog Act） | M2 话语行为头的预训练 |
| DailyDialog | M2 话语行为头的预训练（带 act 和情绪标签） |
| MNLI | M3 的第一段 |
| DialogueNLI | M3 的第二段（人设一致性，和本任务最接近） |
| LIGHT | 文字冒险游戏里的角色对话，可做 M2 的补充预训练 |

### 5.5 标注

核心协议、抽样、标注界面和标签用法见 [annotation.md](annotation.md)：标注者读到第 k 次决策之前的内容，比较当时同一层的两个匿名候选，不显示后文，也不显示 DM 的实际选择。

- Console 的 Annotate 现在只有 pairwise。要新增四种界面：玩家输入的多头标注（含切分和合规）、段落四分类、张力窗口打分、误拒复核（被拒后玩家坚持原意的输入）。
- 6 个人都参与人工标注。20% 的样本重叠标注，用来算一致度。
- 每种标注写一页标注指南，和数据集一起发布。
- **隐私**：课程政策禁止把可识别的个人信息放进任何 AI 工具。游戏会让玩家输入名字，而这个名字会发给 LLM API，所以**真人游玩和用户研究一律用化名**。

---

## 6. 评估

### 6.1 研究问题

| RQ | 问题 | 主要指标 | 对比对象 |
|---|---|---|---|
| RQ1 | 学出来的奖励模型，是否比 Façade 公式和零样本 LLM 更符合人的判断，也更贴目标张力弧？ | 人工测试集准确率；留出 beat 上的准确率；Baseline check；用 M4 测的弧误差 | A、B、C-MLP、C-LoRA |
| RQ2 | 小模型能否以很低的延迟和成本，复现 LLM 老师的判断？ | 学生对老师的一致率、对人工的指标、延迟、每局成本 | 四个模块各自的 `llm` 和 `trained` |
| RQ3 | 学出来的守卫能否在不过度拦截的前提下，守住两头：输出侧降低泄密、矛盾和替玩家写（M3），输入侧拦住越权输入（M2 合规头）？ | 每局泄密率、矛盾率、替玩家写的比例、误拦率；合规头的误拒率和漏拦率 | 守卫关 / `rule` / `llm` / `trained` |
| RQ4 | 用 OOD 分来决定生成新 beat，是否比伪候选打分更会挑时机？ | AUROC；人工对时机的判断 | 伪候选 vs 三种 OOD 方法 |

### 6.2 用户研究

- 约 20 到 30 名同学，每人玩两局：一局用 A，一局用 C。顺序随机，双盲。每局约 25 分钟，两局约 50 分钟。
- 局后问卷：agency、连贯性、紧张感、"NPC 有没有说漏嘴"、"叙述有没有替你做决定"、"被拒的输入拒得合不合理"、整体喜好。
- 全程用化名。

### 6.3 评估套件

`ml/eval/` 一条命令跑完所有离线评估，直接产出报告里的表格和图：混淆矩阵、校准曲线、缩放曲线、张力弧对比图。每份结果都记下用的数据版本和模型版本。

---

## 7. 代码结构与接口

### 7.1 目录

```
backend/
├── app/                 FastAPI + WebSocket（会话循环改成回合循环；协议见 interaction-design.md §11）
├── engine/
│   ├── state/ dsl/ generate/ journal/ llm/     沿用
│   ├── beats/           改：goals 换成步；去掉 repeatable 中间态
│   ├── dm/              改：优先级分层、必接拍
│   ├── clock/           新：剧情时钟、Nora 事件
│   ├── input/           新：整理（切分、翻译、合规、改写）和选项生成
│   ├── reactions/       新：反应层，读 data/reactions.yaml
│   ├── narrator/        新：取代 performer；输出第一人称分段；不输出话语行为
│   ├── world/           改：封闭动作表；动作解析结果在这里落成状态变化；NPC 阻拦、换房间、跟随
│   ├── illustrate/      新：tableau → 取缓存或生图（异步）
│   └── models/          新：四个模块的运行时适配层
│       ├── scorer.py    rule | llm | trained   （原 dm/scorers 搬过来）
│       ├── encoder.py   rule | llm | trained
│       ├── guard.py     rule | llm | trained
│       └── tension.py   rule | llm | trained
├── ml/
│   ├── data/            从日志构建版本化数据集；扰动样本生成
│   ├── models/          四个模块的网络定义
│   ├── train/           训练脚本（Kaggle notebook 直接调用）
│   ├── eval/            离线评估套件
│   ├── serve/           推理服务：加载注册表里的权重，批量推理
│   └── registry/        <模块>/<版本>/{权重, model_card.md, metrics.json, data_version}
└── selfplay/            改：5 种人格、探索策略
```

### 7.2 统一接口

```python
class Scorer:            def score(self, state, dialogue, candidates) -> list[float]
class Encoder:           def encode(self, turn_input, context) -> EncoderOutput  # segments, units[act, addressee, topics, action], suspicion, claims, validity, ood
class Guard:             def check(self, segment, kind, state, player_input) -> GuardVerdict  # label, fact or span, confidence
class TensionEstimator:  def estimate(self, window, state=None) -> float
```

- 选哪一路由环境变量决定，例如 `MODEL_SCORER=trained@v3`、`MODEL_GUARD=llm`。
- 影子模式由 `MODEL_SHADOW=1` 打开。

### 7.3 日志新增字段

- 新增每回合一条的回合日志，字段见 interaction-design.md §13。
- 每条决策日志和回合日志都加两样：
  - `model_versions`（含 prompt 版本）
  - 四个模块三路实现的全部输出（影子模式下）

### 7.4 Console

- **Decision Log**：沿用，显示 A/B/C 三路分数。
- **新增回合检查器**：每回合一行，展开后看原文、整理草稿、合规判定、M2 单元、反应候选和选中项、数值变化、步指针、叙述者分段、M3 判定、选项和各阶段延迟（interaction-design.md §10.7）。
- **新增 Models 标签页**：每回合输入的 M2 输出、每段文字的 M3 判定、M4 测出的张力曲线叠在目标弧上。
- Poster 的截图和现场演示都从这里来。

---

## 8. 算力

| 资源 | 用途 |
|---|---|
| Kaggle（每个账号每周约 30 GPU 小时，6 个人就是 6 个账号） | 所有训练 |
| Azure for Students（$100） | 备用；或者在用户研究期间跑推理服务 |
| 本地 CPU | M2、M3、M4 的推理；M1 用 0.5B 时也够 |

粗略估计，以实测为准：

- DeBERTa-base 级的 M2、M3、M4，每次训练 1 GPU 小时上下；
- 0.5B 的 M1 加 LoRA，每次 1 到 3 GPU 小时；
- 1.5B 加 QLoRA，每次 4 到 8 GPU 小时，只做消融。

---

## 9. 六人分工

| # | 角色 | 负责 | 交付物（互评的依据） |
|---|---|---|---|
| 1 | M1 与 DM 集成 | 奖励模型、scorer 接口、GENERATE_NEW 重排 | M1 结果表、缩放曲线 |
| 2 | M2 | 编码器、切分、合规、动作解析、OOD | M2 结果表、合规头的误拒率、OOD 的 AUROC |
| 3 | M3 | 守卫、知识卡、扰动数据生成 | M3 结果表、泄密率和替玩家写的比例对比 |
| 4 | M4 与评估 | 张力估计器、评估套件、用户研究 | M4 结果、弧对比图、用户研究报告 |
| 5 | 数据 | 自博弈、标注界面、数据集构建与发布 | Fragile-DM 各版本、数据卡、标注一致度 |
| 6 | 故事与前端 | beat 池、state_v2、文字前端、插图 | beat 池、可玩的演示 |

人工标注全员参与。中期报告的文献综述按模块分头写。

---

## 10. 时间线

| 周 | 日期 | 目标 | 课程节点 |
|---|---|---|---|
| 1 | 10/5–10/11 | 最小 beat 池（约 15 个）、state_v2、动作表、反应表；回合循环和叙述者；自博弈改成新故事；标注 prompt | pre-proposal 已交 |
| 2 | 10/12–10/18 | 自博弈第一轮（约 100 局）；标注界面；外部数据预训练开始 | |
| 3 | 10/19–10/25 | 自博弈加量到约 300 局；M1、M2、M3 第一版；人工标注第一轮（500 对、1000 条话语） | |
| 4 | 10/26–11/1 | 第一轮 M4 标注；beat 池扩到 30 个以上 | 11/2 期中考试，本周放轻 |
| 5 | 11/2–11/8 | 中期报告：数据集 v1 统计、M1/M2 初步结果、文献综述 | 11/9 中期报告截止 |
| 6 | 11/9–11/15 | 用训练好的模型跑第二轮自博弈（on-policy）；M3、M4 第二版；全部消融 | |
| 7 | 11/16–11/22 | 用户研究；缩放曲线；poster 初稿 | 11/16 Quiz 2 |
| 8 | 11/23–11/29 | Poster 定稿；演示加固 | |
| 9 | 11/30 | Poster session | |
| 期末 | | 最终报告 | |

**关键路径是数据。** 自博弈不依赖前端，所以第 1 周只要最小 beat 池和 state_v2 就能开跑，故事和前端可以边跑边补。

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| beat 池迟迟写不完，数据跑不起来 | 第 1 周先用最小 beat 池开跑；其余 beat 由 `/author` 流水线加 LLM 起草、编剧审阅 |
| 老师不认可自建数据集 | 第 2 周前在 office hour 或 Piazza 确认；外部数据集的迁移实验本身也是结果 |
| judge 和人工的一致率低 | 调 judge 的 prompt，加人工标注；一致率本身就是报告里的一个结果 |
| M1 没有超过 B | 照实报告，负结果加上缩放曲线和 C-MLP 的分析，仍然是一篇完整的报告 |
| M3 拦得太多，把戏拦死 | 阈值在人工测试集上按误拦率校准，误拦率和泄密率一起报 |
| 合规头拒得太多，玩家没有自主感 | 只拒越权、离谱、越界和戏外输入，合理的尝试一律放行（interaction-design.md §4.1）；按误拒率校准；被拒后坚持原意的输入进复核队列 |
| 叙述者替玩家做决定 | 叙述者规则（story.md §11）加上 M3 的 player_overreach 一类 |
| 一回合要串行调用整理、叙述者和 M3，mock 阶段每回合要等 6 到 10 秒 | 生成时玩家本来就不能输入，界面显示等待；原样确认的草稿复用整理时的分类；训练好的模型替换后延迟会大幅下降，这本身就是 RQ2 的结果 |
| API 成本超支 | 自博弈用便宜模型；能缓存的都缓存；影子模式只在采数据时开 |
| 玩家名字等个人信息进入 LLM | 真人游玩和用户研究一律用化名 |

---

## 12. 待定

| # | 问题 | 建议 |
|---|---|---|
| B1 | 代码放哪：继续在 Wrongest Person 仓库里改，还是在 `Fragile/` 下新开仓库，把后端 engine、selfplay 和 tests 拷过来 | 新开仓库。前端的 Phaser、地图和立绘整块不要了，留在老仓库里只会是负担 |
| B2 | 基座模型的具体型号（M1 用哪个 0.5B / 1.5B） | 第 2 周按当时可用的开源模型定 |
| B3 | 老师 / judge 用哪家 LLM | 沿用 Wrongest Person 的分工思路：便宜模型做叙述者和自博弈，强模型做 judge |
| B4 | 剧情侧的待定项 | D1 已定为 T2，游戏和训练数据都只用 T2；其余见 story.md §14 |
