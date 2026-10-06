# 易碎品 Fragile

> 剧情设定文档 v0.2 · 2026-10-06（按 interaction-design.md 改成回合制）
> 状态：故事方向已定。标【待定】的项还没拍板，文档里先写了默认值。
> 来源：以《夺魂索》Rope（Patrick Hamilton 1929 剧本 / Hitchcock 1948 电影）为骨架，拼接《罪恶之家》An Inspector Calls（人人有份）和《竹林中》（各说各话）的结构。
> 取代：Wrongest Person 仓库（`D:\OtherProjects\WrongestPerson`）里的 `story/WrongestPerson_Screenplay_BiyingZeng.pdf`。玉楼酒家场景、地图和美术整体弃用。
> 配套：[interaction-design.md](interaction-design.md)（交互设计）、[backend-design.md](backend-design.md)（后端与学习模块设计）。
> 交互形态：回合制纯文字。玩家每回合写自己的言行，系统写一段第一人称的故事，关键画面配插图。开局只输入名字和性别。详见 [interaction-design.md](interaction-design.md)。

---

## 0. 一句话

明早 Julian 和 Mia 就要移民。今晚的送别宴摆在一只等着海运的木箱上。被邀请的老朋友 Leo 没来。他下午来过，现在就在箱子里。

---

## 1. 为什么是这个故事

| 架构要求 | 本故事怎么满足 |
|---|---|
| 一个场景、一幕 | 一套搬空的公寓，一顿晚饭；剧情时间约 18 分钟，约 14 拍、26 回合 |
| 情节放在过去，现在只是对话 | 命案在下午已经发生，晚上只有吃饭、聊天和私下谈话 |
| 2 到 3 个同场 NPC，拉玩家站队 | Julian 和 Mia 全程在场，各自想把你拉进自己的版本；Nora 在最后登场 |
| 每个 NPC 都有秘密，分层且互相咬合 | 每人三层秘密，先用小秘密掩护大秘密 |
| 玩家身份很薄 | 大学时的朋友，只输入名字和性别 |
| 结局由累积状态决定 | 你站在谁那边、揭开了多少、谁先崩溃、你对 Nora 说了什么 |
| 剧情时钟 | Nora 先发消息，再打电话，然后到楼下，最后敲门；剧情时间每过一个 beat 加 n，不按真实时间 |
| 物件是话题的触发器 | 木箱、两部手机、楼下的车、合影、第四副碗筷 |

和 Façade 的继承关系：Grace 和 Trip 在客人面前表演"我们婚姻很好"，Julian 和 Mia 在你面前表演"今晚什么都没发生"。整场戏就是这层表面一点点裂开。

---

## 2. 基调与风格

- 希区柯克式悬疑，带黑色幽默。可怕的事实叠在日常的礼节上：坐在尸体上吃外卖，为"缺席的朋友"干杯。
- 主要引擎是戏剧反讽。玩家越来越怀疑，人物越来越用力地表演正常。
- 不靠血腥。尸体始终不直接出现，就算开箱，描写也停在"你看见了一只鞋"这一层。
- 崩溃要克制。越接近真相，人反而越安静、越礼貌。Façade 的人物"自我中心"，所以可以忽略玩家的话；这里的人物"忙着表演"，所以可以合理地岔开话题。

---

## 3. 人物

### 3.0 关系

```
            大学时的同一个圈子
   ┌──────────────┬──────────────┬──────────────┐
  你            Mia ──夫妻── Julian           Leo
 （这几年      （和 Leo 认识   （毕业后和 Leo   （Mia 最早的朋友，
  联系少了）    得最早）        合开工作室）     Julian 的合伙人）
                                                 │
                                               Nora（妹妹）
```

【待定 D2】Julian 和 Mia 的关系，默认是夫妻。

### 3.1 你（玩家）

- 只输入名字和性别。NPC 用名字称呼你，代词跟随性别。
- 每回合只写自己的言行：台词、动作、神态，以及对谁说。别人的言行、世界里有什么、尝试的结果都由系统决定（interaction-design.md §3–4）。
- 身份：大学时的朋友，这几年联系少了。故事不替你写性格，也不替你写经历。
- 唯一写好的过去：今天 15:10，Leo 给你打了两次电话，你没接。他留了一条语音，你还没听（全文见 §7.4）。【待定 D3】
- Leo 最信任的人是你。这一点只通过那条语音透露。
- 插图里不出现你。所有画面都是你的第一人称视野。

### 3.2 Julian

| | |
|---|---|
| 年纪 | 三十出头 |
| 身份 | Mia 的丈夫，和 Leo 合开一家小设计工作室 |
| 表面 | 从容、风趣，一副主人的样子。一直倒酒、讲笑话，把话题拉回"我们的新生活" |
| 今晚想要的 | 平安送走你，让你成为"那晚一切正常、Leo 没来"的证人 |
| 最怕的 | Mia 崩溃 |
| 秘密 L1 | 移民是上周才决定的。这是掩护用的小秘密，他会主动说："Spontaneous. You know me." |
| 秘密 L2 | 他挪用了工作室的钱，出国其实是跑路。Leo 发现了 |
| 秘密 L3 | 下午和 Leo 动了手，具体版本见 §5.2 |
| 诱饵 | 先给你打预防针："Mia hasn't been well. If she says strange things tonight, be kind to her." |
| 怀疑但不确定的事 | 下午 Leo 说"有人打电话叫我来的"，没说是谁。Julian 猜是 Mia，但不敢问 |
| 后台行为 | 给每个人倒酒，自己的杯子永远是满的；整晚穿着外套不脱，因为 Leo 的手机在口袋里；时不时看表 |
| 破绽 | 越紧张越幽默；说谎时会叫你的名字；能不说 Leo 的名字就不说，用 "he" 或 "our friend" 代替 |
| 说话方式 | 短句、反问、玩笑 |
| 绝不会说 | dead、body、afternoon |

台词样例：

- "The table left on Tuesday. The crate is sturdier anyway."
- 被问箱子里装了什么："Books. And the bodies of my enemies." 说完自己先笑。这句只能在前半场说。
- "He'll turn up. He always turns up late and apologizes beautifully."
- 解释外套："We cancelled the heating already." Mia："No we didn't."

### 3.3 Mia

| | |
|---|---|
| 年纪 | 三十出头 |
| 身份 | Julian 的妻子，认识 Leo 比认识 Julian 早 |
| 表面 | 热情、过分周到，但心不在焉。一直在擦东西：台面、杯子，还有本来就干净的地方 |
| 今晚想要的 | 有一个人知道真相，同时不毁掉她 |
| 最怕的 | 被 Julian 抛下；坐牢；Leo 的妹妹 |
| 秘密 L1 | 她不想走。掩护用："Julian and I are... It's fine. It's a fresh start." |
| 秘密 L2 | 下午是她背着 Julian 打电话叫 Leo 来的。她以为 Leo 能逼 Julian 把钱还上、留下来 |
| 秘密 L3 | 见 §5.2 |
| 诱饵 | 在厨房里对你半坦白婚姻出了问题，用来解释她为什么失态 |
| 后台行为 | 反复擦厨房岛台的同一个角；不坐木箱的那一头；反复确认窗户关好了 |
| 破绽 | 会突然问很具体的问题，比如 "Did you come by car? Where did you park?"，因为她在担心楼下那辆车；说起 Leo 会先用过去时，再改口 |
| 说话方式 | 长句，说到一半自己打断，经常道歉 |
| 绝不会说 | 下午的具体时间 |

台词样例：

- "Leo was always... is always late. God, listen to me."
- "Don't sit there. That end is wobbly."
- "Can I get you anything? Anything at all?"

### 3.4 Leo（缺席）

- 只通过物件和别人的嘴存在：语音留言、楼下的黄色旧车、墙上的合影、手机震动、两个人的回忆。
- 回忆里的 Leo：总迟到，讨人喜欢，借钱不还，会为了朋友半夜开两小时车。
- 真实动机：他不是来揭发 Julian 的，是来要他那份钱的，这是 Nora 怂恿的。这一点只在最深一层揭露，用来打破"Leo 是纯粹的受害者"这个印象。

### 3.5 Nora（后到）

| | |
|---|---|
| 身份 | Leo 的妹妹，二十多岁，急性子，说话直 |
| 怎么找来的 | Leo 跟她说过今晚和你一起在 Julian 家吃饭；Leo 的共享定位显示在这栋楼；楼下停着 Leo 的车 |
| 今晚想要的 | 找到哥哥 |
| 秘密 | 是她怂恿 Leo "go get what's yours before he runs"。知道 Leo 死了以后，她自己也有一份 |
| 戏剧功能 | 把"要不要说出来"从一个抽象的道德问题变成一张具体的脸。她站在门口的时候，你说的每一句话都是证词 |

她先只通过你的手机出现（短信、电话），最后才敲门进来。详见 §7.1。

---

## 4. 场景：搬空的公寓

| 区域 | 有什么 | 戏剧用途 |
|---|---|---|
| 客厅 | 木箱（当餐桌用，铺着桌布，四把折叠椅）、一摞纸箱、墙上唯一没摘的合影（你们四个，大学时）、窗外的街 | 主舞台，第一阶段几乎都在这里 |
| 开放式厨房 | 大理石岛台（Leo 撞上的就是那个角）、漂白水味、少了一块地垫、一袋垃圾 | 和 Mia 私下说话。她会先打开水龙头，再压低声音（interaction-design.md 待定 I3） |
| 阳台 | 能看见楼下的街和那辆黄色旧车；Julian 在这里抽烟 | 和 Julian 私下说话 |
| 玄关 | 前门、门上贴着 "MOVERS 6 AM"、标着 TOOLS 的纸箱（电钻和螺丝刀）、柜台上的机票和护照 | Nora 敲门的地方；开箱的工具在这里 |
| 浴室、卧室 | 门关着。浴室里有一袋湿毛巾 | 主人会把你挡回去（"The plumbing's packed."） |

- 晚饭是外卖，来自你们大学时常去的那家店，是 Julian 点的，也是 Leo 最爱的那家。
- 搬家公司明早 06:00 来取木箱，航班是明早 07:40。你今晚一走，证据天亮就没了。

---

## 5. 过去：真相

### 5.1 时间线

| 时间 | 发生了什么 |
|---|---|
| 几个月前 | Julian 从工作室账上挪走一大笔钱，去填自己的投资亏空 |
| 两周前 | Leo 发现账不对，私下问 Julian。Julian 说会补上 |
| 上周 | Julian 宣布移民，订了明早 07:40 的航班和海运 |
| 昨天 | Leo 告诉了 Nora。Nora 说："Go get what's yours before he runs." |
| 今天 14:00 | Mia 背着 Julian 给 Leo 打电话："He's leaving tomorrow. If you want to stop him, come now." |
| 15:10 | Leo 在路上给你打了两次电话，你没接。他留了语音 |
| 15:30 | Leo 到了。他没提报警，只要钱，还说"有人打电话叫我来的"。三人在厨房吵起来，扭打中 Leo 的头撞上岛台的角 |
| 15:40 | Leo 没了呼吸。两个人没有叫救护车 |
| 16:00–18:30 | 清理厨房，扔掉沾血的地垫；把原来箱子里的书塞进别的纸箱，把 Leo 装进木箱，拧上螺丝。Leo 的手机静音后放进 Julian 的外套口袋。车钥匙在 Leo 自己身上，所以车还停在楼下 |
| 18:45 | 两人决定照常开送别宴，因为取消反而可疑。桌上故意摆了四副碗筷，打算当着你的面撤掉一副，作为"Leo 放鸽子"的证据 |
| 19:00 | 你按响门铃 |

### 5.2 谁动的手：T2，Mia 打的

| 实际发生了什么 | Julian 的版本 | Mia 的版本 |
|---|---|---|
| Leo 掐住 Julian，Mia 用威士忌瓶砸了 Leo，Leo 倒下时撞上岛台 | "是我。是我推的。"（顶罪，为了保护 Mia） | 先说"我不记得了"，崩溃后承认 |

规则：

- 游戏和训练数据都只用 T2。
- 不管是谁砸的那一下，两人都有一份共同的罪责：没叫救护车、藏尸、对你撒谎。所以最后的道德判断始终有分量。
- 叙述者只拿到每个人"知道什么、会说什么"，并且每回合只拿到其中已经可以说的部分（interaction-design.md §9.3）。

弃用的备选，只留作记录，不进游戏也不进训练数据：

- T1 Julian 推的：扭打中 Julian 推了 Leo。Julian 先说"他自己滑倒的"，被逼到底才承认；Mia 说"Julian 推的，我看见了"。
- T3 没人知道：三个人扭成一团，Leo 倒下了，两人都以为是对方，各自真心指认对方。

### 5.3 人人有份

| 人 | 他的那一份 |
|---|---|
| Julian | 偷钱、和 Leo 扭打、藏尸、替 Mia 顶罪 |
| Mia | 叫 Leo 来、用酒瓶砸了 Leo、帮着藏尸 |
| Leo | 是来要钱的，不是来讲道理的 |
| Nora | 怂恿他去要 |
| 你 | 没接那两个电话 |

### 5.4 谁知道什么

这张表是叙述者和 M3 保持一致的依据。任何人都不能说出自己不知道的事，也不能对自己没听到的话作出反应。

| 事实 | Julian | Mia | Nora | 你（开局时） |
|---|---|---|---|---|
| Julian 挪用了钱 | 知道 | 知道 | 知道（Leo 说的） | 不知道 |
| 是 Mia 叫 Leo 来的 | 怀疑，不确定 | 知道 | 不知道 | 不知道 |
| Leo 是来要钱的 | 知道 | 知道 | 知道（是她怂恿的） | 不知道 |
| Leo 下午来过 | 知道 | 知道 | 不知道 | 不知道 |
| Leo 已经死了，在箱子里 | 知道 | 知道 | 不知道 | 不知道 |
| 是 Mia 砸的那一下 | 知道（替她顶罪） | 知道（先说不记得） | 不知道 | 不知道 |
| Leo 给你打过电话 | 不知道 | 不知道 | 不知道 | 手机里有，但还没看 |
| Leo 的车在楼下 | 知道（钥匙在箱子里，挪不走） | 知道，并且一直在担心 | 到楼下时才知道 | 开场旁白里一闪而过 |

---

## 6. 今晚的结构

### 6.1 三个阶段

**第一阶段：表演正常（剧情第 0–6 分钟，约 4 拍）**

- 迎客，在木箱上吃晚饭，撤掉第四副碗筷，打包时拌嘴，回忆大学。
- 你不知道箱子里有什么，紧张感来自你从细节里察觉出的不对劲。
- 两个人拌嘴逼你站边，拌的内容全都暗指下午的事，比如 "You always make me clean up your mess."
- 你可能注意到的：楼下的车、Julian 不脱外套、Mia 不坐木箱那一头、手机里有未接来电。

**第二阶段：裂缝（剧情第 6–12 分钟，约 4 拍）**

- 两人轮流把你拉进厨房或阳台私下说话，各抛一个小秘密作掩护，并抢先给对方打预防针。两场私谈的顺序可以互换。你也可以主动叫其中一个人去私下说话。
- 线索：漂白水味、少了的地垫、浴室的门、手机在震、机票。
- 中点危机：两人当着你的面说出了两个对不上的下午。

**第三阶段：摊牌（剧情第 12–18 分钟，约 6 拍）**

- "Leo 死了"被说出来或被你发现。揭开的路径有好几条（见 §8 的 `the_admission`）。
- 两人各给一个版本，就像《竹林中》。
- 然后是交易：Julian 要你当证人，必要时威胁说"我们会说你下午也在"；Mia 求你。
- Nora 到了楼下，然后敲门，问你 Leo 在哪。你的回答就是证词。结局。

### 6.2 目标张力弧（给 `tension_curve.yaml`）

横轴是剧情分钟，不是真实时间，也不是决策序号。

| 剧情分钟 | 张力 | 说明 |
|---|---|---|
| 0–3 | 1 | 热情的表面 |
| 3–6 | 1 → 2 | 细节开始不对 |
| 6–10 | 2 → 4 | 私谈、手机震动，中点危机冲到 4 |
| 10–12 | 回落到约 3.5 | 一段安静：倒酒、回忆 Leo |
| 12–17 | 4 → 5 | 摊牌、交易、Nora 在楼下、敲门 |
| 结局 | 回落 | 尾声 |

---

## 7. 时钟与物件

### 7.1 Nora 线（`nora_pressure` 0–4）

时间线不是现实的时间，时间本身是一个变量：每过一个 beat，当前时间 +n。n 由 beat 自己声明，各阶段的默认值见 interaction-design.md §7.1。

| 等级 | 剧情分钟 | 发生什么 |
|---|---|---|
| 0 | 开局 | 无 |
| 1 | 5 | 给你发短信："Hey, is Leo with you? He's not picking up." |
| 2 | 9 | 给你打电话。下一回合你决定接不接；接了由必接拍 `noras_call` 接上，Nora 只有声音，不在场。她也开始反复打 Leo 的电话，Leo 的手机因此在 Julian 的外套里震 |
| 3 | 13 | 短信："I'm downstairs. His car is here. His location says he's in your building."（必接拍 `downstairs`） |
| 4 | 16 | 敲门（必接拍 `the_knock`）。Nora 进门，三人戏开始 |

- 某一拍结束、时钟跨过了哪一级的分钟数，那一级就在这个回合触发。事件写进同一段正文，短信和来电也同时出现在你的手机里（interaction-design.md §7.3）。第 40 回合是安全上限，到了直接敲门。
- 你怎么回 Nora 是全剧最重的动作之一，会写进 `nora_told`：没回、撒谎、说了真话。给 Nora 发短信用的是你自己的手机，没人拦得住。
- 主人会注意到你在看手机："Who's texting you?"

### 7.2 Leo 的手机（`leo_phone`）

- 状态：in_jacket / buzzed / found。
- 任何人打 Leo 的电话，Julian 的外套就会震。可能是你主动打的，也可能是 Nora 到了第 2 级以后在打。
- Julian 的反应：找借口离开房间，或者去阳台"接个工作电话"。
- 你第一分钟就打，第一分钟就会出事：外套一震，就由必接拍 `the_buzz` 接上（interaction-design.md §6.5）。

### 7.3 木箱（`crate`）

- 状态：sealed / opened。
- 螺丝拧死了，要用玄关 TOOLS 箱里的螺丝刀或电钻，空手拧不开。
- 开箱在一回合内结算，没有确认步骤。Julian 或 Mia 在场、而且镇定值不低于阈值时，会拦住你；被拦的人镇定值下降，所以一再尝试会越来越难被拦住（interaction-design.md §6.6）。
- 打开以后不可逆，由必接拍 `the_admission` 接上。
- 开箱后的描写停在"一只鞋"。

### 7.4 你的手机

- 开局有两个来自 Leo 的未接来电（15:10）和一条没听的语音。开场旁白会提一句"手机下午震过"。
- 语音全文：

  > "Hey, it's Leo. I'm heading over to Julian's now, early. Something's... I'll explain. Can you come early tonight? Like, really early. Call me back. Please."

- 它会引起怀疑，但不直接揭露什么。听完以后，`revealed` 加入 `missed_call`。之后 Nora 的消息也从这部手机进来。
- 打开手机看列表不用掉回合；听语音、回短信、打电话都要用掉一回合，主人看得见你在用手机（interaction-design.md §3.6）。

### 7.5 其他物件

| 物件 | 在哪 | 用途 |
|---|---|---|
| 第四副碗筷 | 木箱上 | Julian 当着你的面撤掉："He's not coming. Classic Leo." 撤的那一下 Mia 会瑟缩 |
| 合影 | 客厅墙上，唯一没摘的东西 | 降温话题（大学往事）；给玩家一段共同的过去，而不用写背景 |
| 黄色旧车 | 楼下，两个轮子压在路沿上 | 开场旁白里出现；从阳台能看到；Mia 会问你停在哪；Nora 的线索 |
| 漂白水味、少了的地垫 | 厨房 | "We spilled wine." |
| 浴室的湿毛巾 | 浴室 | 主人阻止你进去 |
| 机票、护照 | 玄关柜台 | 07:40，Julian 很急 |
| Julian 的外套 | 一直穿在他身上 | 关于暖气的小矛盾；手机在里面 |
| 外卖 | 木箱上 | Leo 最爱的那家店，带反讽 |

---

## 8. 社交游戏与状态

### 8.1 四个社交游戏

| 游戏 | 来源 | 在本故事里是什么 |
|---|---|---|
| 站队 | Façade 的 affinity 游戏（零和） | 你偏向 Julian 的版本还是 Mia 的版本 |
| 离间 | 新加的 | 两人还站不站在一起。最大的楔子是"是 Mia 叫 Leo 来的"被 Julian 知道 |
| 话题深挖 | Façade 的 hot-button，三层 | 木箱、Leo、钱和移民、下午、婚姻、大学 |
| 坦白 | Façade 的 therapy 游戏 | 每个人离开口还有多远 |

这四个游戏的数值怎么随你的输入变化，由反应层定义，见 interaction-design.md §5。

### 8.2 状态变量（草稿，将来写成 `schemas/state_v2.json`）

| 变量 | 类型 | 说明 |
|---|---|---|
| `tension` | 0–5 | 总张力 |
| `julian_composure` | 0–1 | 低于阈值会说漏嘴、会失控 |
| `mia_composure` | 0–1 | 低于阈值会坦白 |
| `side` | −2..+2 | −2 完全站 Julian，+2 完全站 Mia |
| `couple_unity` | 0–3 | 3 是口径一致，0 是互相指认 |
| `player_suspicion` | 0–3 | 玩家表现出来的怀疑程度，从言行推断 |
| `topic_tier.<topic>` | 0–3 | crate / leo / money / afternoon / marriage / college |
| `revealed` | 集合 | car_downstairs, missed_call, leo_was_here, embezzlement, mia_called_leo, leo_wanted_money, leo_dead, body_in_crate, who_struck, nora_pushed_leo |
| `nora_pressure` | 0–4 | 见 §7.1 |
| `nora_told` | none / lie / truth | 你对 Nora 说了什么 |
| `crate` | sealed / opened | |
| `leo_phone` | in_jacket / buzzed / found | |
| `player_phone` | unchecked / voicemail_heard | |
| `nora_call` | none / ringing / answered / declined / missed | Nora 第 2 级的来电 |
| `player_room` `julian_room` `mia_room` | living / kitchen / balcony / hall / bathroom | |
| `story_min` | 浮点 | 剧情分钟，每过一个 beat +n；取代原来的 `clock_s` |
| `turn` | 整数 | 回合数 |
| `beat_step` `beat_turns` | 整数 | 当前 beat 的步指针、已用回合 |
| `silence_streak` | 整数 | 连续沉默的回合数 |
| `claims` | 列表 | 你在台词里声称知道的事实、对谁说、第几回合；不进 `revealed` |
| `heard_by` | 映射 | 每条私下的话被谁听到 |
| `beat_history` `story_phase` `consecutive_generated` | | 沿用现有定义 |

### 8.3 话题的三层

| 话题 | 第 1 层 | 第 2 层 | 第 3 层 |
|---|---|---|---|
| 木箱 | "Books. Customs paperwork is a nightmare." | 你一碰它，Julian 就烦躁；Mia 让你别把杯子放在那一头 | "Please. Not the crate." |
| Leo | "He flaked." | Mia 说漏了过去时；Julian 不肯说他的名字 | "When did you last see him?" 两人的说法开始打架 |
| 钱和移民 | "A fresh start." | "The studio's not doing great." | 挪用公款 |
| 下午 | "We spent all day packing." | 两人说的时间对不上 | 两个版本 |
| 婚姻 | 互相开玩笑 | Mia："We're not okay." | Julian："Ask her why he always calls her."（转移视线） |
| 大学 | 合影、旧店的外卖 | Leo 的旧事 | Leo 半夜开两小时车来帮朋友。这个话题只降温，不升温 |

层级怎么推进、每个阶段的上限是多少，见 interaction-design.md §5.4。

---

## 9. Beat 池（初稿）

斜率是对 `tension` 的作用。前置条件这里只写大意，正式写成 DSL 时再细化。正式写的时候，每个 beat 写成 2 到 4 步，并声明自己占多少剧情分钟（`minutes`），结构见 interaction-design.md §6–7。标"必接"的拍在触发条件成立时直接接上，不经过打分器（§9.4）。

### 9.1 第一阶段：表演正常

| id | 名称 | 类型 | 斜率 | 戏剧意图 |
|---|---|---|---|---|
| `the_door` | 迎客 | 主干（开场） | 0 | Mia 开门太快，抱得太久；Julian 端着酒出现 |
| `dinner_on_the_crate` | 木箱上的晚餐 | 主干 | +1 | 核心画面。"The table left on Tuesday." Mia 不坐那一头 |
| `the_fourth_setting` | 第四副碗筷 | 主干 | +1 | 演给你看的"Leo 放鸽子" |
| `packing_quarrel` | 打包拌嘴 | 卫星 | ±1 | 拌嘴里藏着下午的事，逼你站边 |
| `college_days` | 大学往事 | 卫星 | −1 | 合影、外卖；读者知道 Leo 就在箱子里 |
| `why_leave` | 为什么突然要走 | 卫星 | +1 | Julian 说"spontaneous"，Mia 沉默 |
| `to_absent_friends` | 为缺席的朋友干杯 | 卫星 | +1 | Julian 举杯，Mia 喝不下去 |
| `the_jacket` | 外套 | 卫星 | +1 | 暖气的小矛盾 |
| `wobbly_end` | 晃的那一头 | 卫星 | +1 | 你想坐或想放东西在那一头，Mia 拦住 |

### 9.2 第二阶段：裂缝

| id | 名称 | 类型 | 斜率 | 戏剧意图 |
|---|---|---|---|---|
| `mia_in_the_kitchen` | 厨房里的 Mia | 主干 | +1 | 借洗碗把你拉走；用婚姻问题当诱饵；一直擦岛台的那个角 |
| `julian_on_the_balcony` | 阳台上的 Julian | 主干 | +1 | 抽烟，抢先给 Mia 打预防针；你往下看能看见那辆车 |
| `the_buzz` | 手机在震 | 主干（必接） | +2 | Julian 外套里的手机一震就接上：Nora 到第 2 级后在打，或者你打了 Leo 的电话；Julian 离席 |
| `noras_call` | Nora 的电话 | 主干（必接） | +1 | 你接了 Nora 的电话。她问 Leo 在哪，两个主人在旁边听着。你在电话里说的话会写进 `nora_told` |
| `two_afternoons` | 两个下午 | 主干（中点危机） | +2 | 两人当着你的面对不上口径，场面爆掉 |
| `bleach` | 漂白水 | 卫星 | +1 | 气味、少了的地垫、"we spilled wine" |
| `whose_car` | 谁的车 | 卫星 | +1 | Mia 问你停在哪。你一提黄色的车，两人都僵住 |
| `the_bathroom_door` | 浴室的门 | 卫星 | +1 | "The plumbing's packed." |
| `the_tickets` | 机票 | 卫星 | 0 | 07:40，Julian 看表 |
| `ask_her_why` | 你去问她 | 卫星 | +1 | Julian 把话题引到 Mia 和 Leo 的关系上，用来离间 |
| `the_long_drive` | 两小时的车程 | 卫星 | −1 | Mia 讲 Leo 半夜开车帮朋友，哭了，又收住 |
| `dont_go_yet` | 别走 | 卫星（必接） | +1 | 你想离开，Mia 挡在门口求你留下；Julian 反而帮你拿外套 |

### 9.3 第三阶段：摊牌

| id | 名称 | 类型 | 斜率 | 戏剧意图 |
|---|---|---|---|---|
| `the_admission` | 他没走 | 主干 | +2 | 第一次承认 Leo 死了，由更不镇定的那个人说出来。可能的触发：Mia 的镇定跌破阈值、你开了箱（这时它是必接拍）、手机震过之后你当面质问、你拿语音和车去对质 |
| `the_versions` | 两个版本 | 主干 | +1 | 各说各的：Julian 说是他推的（顶罪），Mia 说她不记得了。两个版本对不上 |
| `the_offer` | 交易 | 主干 | +1 | Julian：当我们的证人，要钱可以给，不然"我们会说你下午也在"。Mia 用另一种方式求你 |
| `who_called_him` | 谁叫他来的 | 卫星 | +2 | 是 Mia 叫 Leo 来的，Julian 知道了。离间到顶 |
| `what_he_wanted` | 他要的是什么 | 卫星 | ±1 | Leo 是来要钱的。打破对 Leo 的单纯同情 |
| `the_quiet` | 安静 | 卫星 | −1 | 承认之后的沉默。Julian 给每个人倒酒，有一种奇怪的温柔 |
| `downstairs` | 楼下 | 主干（必接，剧情第 13 分钟） | +2 | Nora 的短信 |
| `the_knock` | 敲门 | 主干（必接，剧情第 16 分钟） | +2 | Nora 进门："Where is he?" 三人戏开始 |
| `testimony` | 证词 | 主干 | +1 | Nora 当面问你。你说的每一句都是证词，回答决定 `nora_told`，然后接各个结局 |

### 9.4 必接拍（取代原来的打断拍）

回合制下没有打断（interaction-design.md §1）。原来的三个打断拍删除：

- `not_the_crate`：改成开箱时的 NPC 阻拦（§7.3）；
- `give_me_the_phone`：改成报警时 Julian 的阻拦；
- `dont_go_in_there`：改成一条"动作受阻"的全局反应："The plumbing's packed."

取而代之的是必接拍。触发条件成立时，当前这拍在回合末结束，下一拍直接接上，不经过打分器（interaction-design.md §6.5）。同一回合触发多个时，按下表从上到下取第一个。

| 触发 | 接上的拍 |
|---|---|
| 箱子被打开 | `the_admission` |
| 你接了 Nora 的电话 | `noras_call` |
| Julian 外套里的手机震了 | `the_buzz` |
| Mia 把你拦在门口 | `dont_go_yet` |
| 剧情第 13 分钟 | `downstairs` |
| 剧情第 16 分钟，或者第 40 回合 | `the_knock` |

### 9.5 Façade 式全局插入

不属于任何 beat。玩家一提起相应话题，就按 §8.3 的层级插一段，可以插进任何 beat。来源：玩家提到木箱、Leo、钱、下午、婚姻、大学，或者查看合影、车、手机。怎么选、谁来回应、数值怎么变，由反应层决定，见 interaction-design.md §5。

---

## 10. 结局

结局由累积状态决定，不由某一个动作决定。结局判定发生在 `testimony` 之后；提前离开公寓直接进入 `bon_voyage`。

| id | 名称 | 大致条件 | 内容 |
|---|---|---|---|
| `bon_voyage` | 送别 | Nora 敲门时你还不知道真相，或者你提前离开了 | 两人对 Nora 说"他根本没来"，你在场，成了不知情的证人。尾声：清晨六点，木箱被抬走 |
| `the_witness` | 证人 | 你知道真相，偏向主人，对 Nora 撒了谎或者沉默（`nora_told == 'lie'`） | 你成了共犯。尾声：两人登机，你的手机亮了 |
| `open_it` | 开箱 | 当着 Nora 的面揭穿 | 三人戏的高潮。Julian 先把罪揽到自己身上。`couple_unity` 高时他顶到底；低时，比如他已经知道是 Mia 叫的 Leo，他不再护着她，说出是 Mia 砸的。Mia 会不会自己承认，取决于 `side` 和她的镇定值 |
| `confession` | 自首 | 敲门前后，某个人的 composure 被你推到临界点，而你站在他那边 | 由他自己对 Nora 说出来。对应 Façade 的最好结局 |
| `second_crate` | 第二只箱子 | 你单独和 Julian 在一起时把他逼得太紧（`julian_composure` 接近 0，`side` 强烈反他，你威胁要说出去） | 悬念收尾：Julian 锁上门，叫了你的名字。只暗示，不描写 |

生成的结局沿用 Wrongest Person `docs/backend-design.md` §8 的规则：必须标注 `closest_authored_ending`。

---

## 11. 写给叙述者的规则

1. 前半场每个人的最高目标是表演正常。任何直接的问题，先用礼节和玩笑挡回去（Façade 式的转移），不要承认。
2. 不越层。一个人只能说出自己当前层已经解锁的秘密，由 `revealed` 和 `topic_tier` 决定。即兴不得引入新的事实，生成的 beat 也不能改 `revealed`。
3. 每个人只按自己知道的说话（§5.4）。
4. 不直接描写尸体。
5. 玩家写了什么就演什么，可以润色，但不替玩家添加新的话、动作、决定、情绪或内心。感知可以加，但受 `topic_tier` 和 `revealed` 约束（interaction-design.md §9.2）。
6. 用名字称呼玩家，代词跟随玩家选的性别。故事里没有任何情节取决于玩家的性别。
7. 后台行为要持续：Julian 倒酒、穿外套、看表；Mia 擦东西、不坐那一头、看窗户。
8. 台词里不用破折号。
9. 只演反应层选出的反应和当前这一步，不自己挑反应，也不提前演后面的步。

---

## 12. 插图

- 第一人称视角，玩家不入画。
- 先定稿的参考资产：公寓底图（客厅、厨房、阳台、玄关）、Julian / Mia / Nora 的设定图、木箱、合影、黄色旧车。之后每张插图都拿它们做参考，保证一致。
- 关键画面清单：

  | # | 画面 |
  |---|---|
  | 1 | 楼下：雨后的街，黄色旧车压在路沿上（开场） |
  | 2 | 门打开的一瞬，Mia 的笑容 |
  | 3 | 木箱上的晚餐：桌布、外卖盒、四个杯子 |
  | 4 | Julian 撤走第四副碗筷 |
  | 5 | 阳台上，Julian 的烟头，楼下的车 |
  | 6 | 厨房岛台，Mia 的抹布停在那个角上 |
  | 7 | Julian 外套口袋里亮起的光 |
  | 8 | 两个下午：两人隔着木箱对峙 |
  | 9 | 门口的 Nora |
  | 10–14 | 每个结局一张 |

- 出图时机：挂在画面时刻上，也就是 beat 里标记的 `tableau`、`revealed` 变化、换房间、结局，不挂在 beat 边界上。这样不会违反"beat 对玩家不可见"。【待定 D4】
- 作者写的 beat，插图提前离线生成，每个画面按状态出 1 到 3 个变体。只有 GENERATE_NEW 生成的 beat 才现场生图，生不出来就用最近一张兜底。生图是异步的，文字不等图。

---

## 13. 开场旁白（草稿）

第一人称。这是第 0 段的开头，后面接 `the_door` 的开场。

> It stopped raining an hour ago. The street still shines. Out front, a dented yellow hatchback sits under the streetlight with two wheels up on the curb.
>
> My phone buzzed a few times this afternoon. I haven't checked it.
>
> Upstairs, someone has taped a sign to Julian and Mia's door: MOVERS 6 AM.
>
> I ring the bell.

---

## 14. 待定事项

| # | 问题 | 当前默认 |
|---|---|---|
| D1 | 谁动的手 | **已定：T2**。Leo 掐住 Julian，Mia 用威士忌瓶砸了 Leo，Julian 替她顶罪。游戏和训练数据都只用 T2 |
| D2 | Julian 和 Mia 的关系 | 夫妻 |
| D3 | 玩家那两个没接的电话 | 保留 |
| D4 | 插图挂 beat 边界还是画面时刻 | 画面时刻 |
| D5 | 台词语言 | 英文（沿用现有设计） |
| D6 | 标题 | Fragile，备选 Nothing to Declare |

**Wrongest Person 仓库里还描述着旧故事的文件**（代码放在哪里见 [backend-design.md](backend-design.md) §12）：`CLAUDE.md`、`README.md`、`docs/frontend-design.md`（地图、Sprite、立绘、口型都不要了，改成纯文字加插图）、`docs/backend-design.md` §3 状态和 §4 beat 池、`schemas/state_v1.json`、`schemas/messages.json`（纯文字以后的协议）、`backend/data/beats/*.yaml`、`backend/data/interactions.yaml`。

---

## 15. 出处与改编说明

| 来源 | 借了什么 |
|---|---|
| 《夺魂索》Rope | 藏在屋里的尸体、在尸体上吃饭、两个凶手一个稳一个崩、被邀请的客人慢慢察觉 |
| 《罪恶之家》An Inspector Calls | 每个人都有一份责任；在一个家庭场合里被逐一揭开；结局看谁承认 |
| 《竹林中》 | 同一件事，几个当事人各给一个版本 |
| Façade | 两人在客人面前表演一层表面；厨房和阳台的私下谈话；话题分三层；第一人称；玩家只给名字和性别 |
