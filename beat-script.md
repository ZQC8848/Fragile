# Fragile：beat 剧本层 v0（20 拍）

> v0.1 · 2026-10-06 · 草稿；§5 的规则已定，台词和细节待审
> 范围：plan.md M2 的前 20 拍，包括 14 个主干拍、必接卫星拍 `dont_go_yet` 和 5 个结局。其余约 15 个卫星拍后补。
> 依据：[story.md](story.md)（真相 T2）、[interaction-design.md](interaction-design.md)（回合、步、反应层、剧情时钟）。
> 用途：先在这一层把内容定下来，再机械地转成 `data/beats/*.yaml`。台词都是样例，叙述者会围绕它即兴；意图、步、结尾、前提和效果是要定死的。
> 写的过程中定下的几条规则集中在 §5（2026-10-06 已定）。

---

## 0. 约定

### 0.1 初始状态

| 变量 | 初值 | 说明 |
|---|---|---|
| `story_min` / `turn` | 0 / 0 | |
| `tension` | 1 | |
| `julian_composure` | 0.8 | Julian 更稳 |
| `mia_composure` | 0.6 | Mia 更容易崩 |
| `side` / `couple_unity` | 0 / 3 | |
| `topic_tier.*` | 全 0 | |
| `revealed` | 空 | |
| `nora_pressure` / `nora_told` / `nora_call` | 0 / none / none | |
| `crate` / `leo_phone` / `player_phone` | sealed / in_jacket / unchecked | |
| 房间 | 你和 Mia 在玄关，Julian 在客厅 | |

### 0.2 阶段

`story_phase` 由剧情分钟决定：早于 6 分钟是第一阶段，6 到 12 分钟是第二阶段，12 分钟以后是第三阶段。阶段只用来决定话题层级的上限和反应层的规则。

beat 的前提**不按阶段写，按"哪些拍演过了"写**。否则时钟和拍数对不上时会出现没有拍可演的空档。

### 0.3 条目怎么读

- **标题行**：类型 · 阶段 · 斜率 · 分钟 · 最多回合。
  - 斜率沿用 story.md §9。
  - 分钟是这一拍结束时剧情时钟加多少。
  - 效果里的 `tension` 按"斜率 × 0.5"换算（§5 第 1 条）。
- **前提**：先用大白话写，转 YAML 时再写成 DSL。
- **步**：
  - "→ 问你"表示这一步向你提问。站队问题会注明提问的人和沉默算什么。
  - "→ 钩子"表示这一步结尾给你留一个可以回应的东西。
- **本地 mix-in**：括号里是对应的 M2 话语行为或动作，方便转 YAML。
- **台词**：英文，不用破折号；`{name}` 是玩家的名字。
- **插图**：编号对应 story.md §12 的关键画面清单。

### 0.4 黄金路线（合作型、好奇的玩家，Baseline check 用）

| # | beat | 结束时剧情分钟 | 跨过的时钟事件 |
|---|---|---|---|
| 1 | `the_door` | 1.5 | |
| 2 | `dinner_on_the_crate` | 3.0 | |
| 3 | `the_fourth_setting` | 4.5 | |
| 4 | `mia_in_the_kitchen` | 6.0 | 第 5 分钟：Nora 第一条短信 |
| 5 | `julian_on_the_balcony` | 7.5 | |
| 6 | `two_afternoons` | 9.0 | 第 9 分钟：Nora 来电 |
| 7 | `noras_call`（你接了） | 10.0 | |
| 8 | `the_buzz`（Nora 挂了你的电话就去打 Leo 的） | 11.0 | |
| 9 | `the_admission`（你拿车和语音对质） | 12.5 | |
| 10 | `the_versions` | 14.0 | 第 13 分钟：`downstairs` |
| 11 | `downstairs` | 15.0 | |
| 12 | `the_offer` | 16.5 | 第 16 分钟：`the_knock` |
| 13 | `the_knock` | 17.5 | |
| 14 | `testimony` | 18.5 | |
| 15 | 结局（你说了真话 → `open_it`） | | |

---

## 1. 第一阶段：表演正常

### 1. `the_door` · 迎客

主干 · 第一阶段 · 斜率 0 · 1.5 分钟 · 最多 2 回合

**前提**：开局第一拍，接在开场旁白之后。
**地点**：玄关。Mia 开门，Julian 随后从客厅出来。
**意图**：表面热情过了头。Mia 开门太快、抱得太久；Julian 端着两杯酒出来，一副主人的样子。你第一次看到搬空的屋子。

**步**：
1. 门几乎在铃响的同时打开。Mia 抱住你，抱得太久："You came. You actually came." 她的手又冷又湿，像刚洗过东西。
2. Julian 端着两杯酒出现："There they are. Keep your shoes on, we've got nothing left to scratch." 他把你领进客厅：墙上只剩一张合影，其余全是纸箱。Mia 突然问："Did you drive? Where did you park?" Julian 打断她，把酒递给你。→ 钩子：酒递到你手里。

**本地 mix-in**：
- 你问 Leo 来了没有（`ask_about_leo`）→ Julian 抢着答："Not yet. He'll turn up. He always turns up late and apologizes beautifully." Mia 低头看自己的鞋。
- 你提到楼下的黄色旧车（`mention_car`）→ Mia 的笑僵了一下。Julian："Half this street drives a yellow something." `mia_composure −0.1`。
- 你回抱、安慰 Mia（`comfort`）→ 她抱得更紧，然后突然松开，道歉："Sorry. Sorry. Long week."

**效果**：`tension +0`；本拍结束时三人都在客厅。
**插图**：#2 门打开的一瞬，Mia 的笑容。

### 2. `dinner_on_the_crate` · 木箱上的晚餐

主干 · 第一阶段 · 斜率 +1 · 1.5 分钟 · 最多 3 回合

**前提**：`the_door` 演过；三人都在客厅。
**意图**：核心画面。餐桌已经运走，晚饭摆在一只钉死的木箱上，铺着桌布。外卖是你们大学时常去的那家，也是 Leo 最爱的那家。Julian 讲笑话、倒酒；Mia 不坐木箱的那一头。

**步**：
1. Julian 介绍"餐桌"："The table left on Tuesday. The crate is sturdier anyway." 外卖盒摊开，是那家店。
2. 落座。Mia 把你引到另一边："Don't sit there. That end is wobbly." 她自己站着，没坐那一头。
3. Julian 举杯："To fresh starts." Mia 的杯子没举起来。→ 钩子：Julian 转向你："So. What have you been doing with yourself, {name}?"

**本地 mix-in**：
- 你问箱子里装的什么（`ask_about_crate`）→ Julian："Books. And the bodies of my enemies." 他自己先笑了，Mia 没笑。这句只在第一阶段用。
- 你敲箱子、把杯子放在那一头、想坐那一头（动作：`crate` 的 touch / place / sit）→ Mia 抢着把杯子挪开："Not there. Sorry. It's, it's wobbly." `mia_composure −0.1`。
- 你认出外卖、夸外卖（`praise` + 话题 college）→ Julian："Our old place. Ordered extra. In case." Mia 停下筷子。

**效果**：`tension +0.5`。
**插图**：#3 木箱上的晚餐：桌布、外卖盒、四个杯子。

### 3. `the_fourth_setting` · 第四副碗筷

主干 · 第一阶段 · 斜率 +1 · 1.5 分钟 · 最多 2 回合

**前提**：`dinner_on_the_crate` 演过；三人都在客厅。
**意图**：演给你看的"Leo 放鸽子"。撤的那一下，Mia 瑟缩了一下。

**步**：
1. Julian 看表。第四个位子前的碗筷还摆着："Seven forty. Even for him that's ambitious."
2. Julian 把第四副碗筷收走："He's not coming. Classic Leo." 撤走的那一下，Mia 瑟缩了一下。
   → 问你："He does this every time, doesn't he, {name}?"（提问的人：Julian；第一阶段，沉默算中立）

**结尾**：
- Julian 赢（你附和）："See? She thinks I'm being harsh." 他把碗筷放进水槽。Mia 开始擦一块本来就干净的台面。`side −1`。
- Mia 赢（你替 Leo 说话，或者说再等等）：Mia 小声说："He might still come." Julian 笑了一下，碗筷还是收走了。`side +1`。
- 中立：Julian 耸耸肩，把碗筷收走，没再说话。

**本地 mix-in**：
- 你说要给 Leo 打个电话（只是说说，`ask` + 话题 leo）→ Julian："Don't bother. He's probably asleep on someone's couch."（你真的打了，那是动作：Leo 的手机在 Julian 外套里震，必接拍 `the_buzz`。）
- 你问上次联系 Leo 是什么时候（`ask_about_leo`）→ Mia："This morning. No. Yesterday." 两人对视了一眼。`mia_composure −0.1`。

**效果**：`tension +0.5`；`side` 按结尾。
**插图**：#4 Julian 撤走第四副碗筷。

---

## 2. 第二阶段：裂缝

### 4. `mia_in_the_kitchen` · 厨房里的 Mia

主干 · 第二阶段 · 斜率 +1 · 1.5 分钟 · 最多 3 回合

**前提**：`the_fourth_setting` 演过。两种进入方式：
- 被邀请：你和 Mia 都在客厅；
- 你主动来：你和 Mia 都在厨房，Julian 不在厨房。

**意图**：Mia 借洗碗把你拉走，用婚姻出了问题当诱饵，解释自己为什么失态（小秘密 L1：她不想走）。她抢先给 Julian 打预防针。手一直在擦岛台的同一个角。

**开场**：
- 被邀请：Mia 端起外卖盒："Help me with these? He never does." 你答应，两人去厨房；你拒绝，本拍中止，Mia 一个人去厨房；中止的拍以后还能再进（§5 第 4 条）。
- 你主动来：你走进厨房时，Mia 正在擦岛台的那个角。

**步**：
1. Mia 打开水龙头，压低声音。手里的抹布一直在擦岛台的同一个角。
2. 诱饵："Julian and I are... It's fine. It's a fresh start." 停了一下，又说："I don't want to go. Isn't that stupid? Everything's packed and I don't want to go."
3. 预防针："If he says anything about me tonight. About me not being well. You know me, right, {name}?"
   → 问你（提问的人：Mia；第二阶段不能中立，沉默算 Julian 赢）

**结尾**：
- Mia 赢："Thank you. God. Thank you." 她关掉水龙头，眼睛红了。`side +1`。
- Julian 赢（你说她今晚确实不太对劲，或者沉默）："Right. Of course." 她转回去，擦得更用力。`side −1`，`mia_composure −0.15`。
- 本拍结束时，Julian 出现在厨房门口："What are you two whispering about?"（跟随规则）

**本地 mix-in**：
- 你问漂白水的味道、少了的地垫（`ask` + 话题 afternoon，或动作 `kitchen_floor` examine）→ "We spilled wine. Red. It went everywhere." 说得太快。`mia_composure −0.1`。
- 你问 Leo（`ask_about_leo`）→ "Leo was always... is always late. God, listen to me." 话题 leo 升到第 2 层。
- 你问她为什么不想走（`ask_about_move`）→ "Because everyone I have is here." 她看着岛台的那个角。
- 你提到那辆车（`mention_car`）→ "You saw it? The yellow one?" 马上改口："Never mind. Never mind." `mia_composure −0.15`。

**效果**：`tension +0.5`；话题 marriage 升到第 2 层。
**插图**：#6 厨房岛台，Mia 的抹布停在那个角上。

### 5. `julian_on_the_balcony` · 阳台上的 Julian

主干 · 第二阶段 · 斜率 +1 · 1.5 分钟 · 最多 3 回合

**前提**：`the_fourth_setting` 演过。两种进入方式：
- 被邀请：你和 Julian 都在客厅；
- 你主动来：你和 Julian 都在阳台，Mia 不在阳台。

**意图**：Julian 抽烟，把移民讲得像度假（小秘密 L1："Spontaneous. You know me."）。他抢先给 Mia 打预防针。你往下看，能看见那辆车。

**开场**：
- 被邀请："Keep me company? She hates the smoke." 你拒绝，本拍中止，他一个人去阳台。
- 你主动来：你推开阳台门时，Julian 已经靠在栏杆上了。

**步**：
1. Julian 点烟，讲新生活："Spontaneous. You know me. One day you wake up and think, why not." 他看了一眼表。
2. 你往下看：雨后的街，那辆黄色旧车两个轮子压在路沿上。Julian 顺着你的目光看过去，没说话。
3. 预防针："Mia hasn't been well. If she says strange things tonight, be kind to her. Just don't take it to heart, {name}."
   → 问你（提问的人：Julian；沉默算 Julian 赢）

**结尾**：
- Julian 赢："Knew I could count on you." 他拍了拍你的肩。`side −1`。
- Mia 赢（你替 Mia 说话）："Sure. Sure." 他弹烟灰弹得太快，把半截烟扔下了楼。`side +1`，`julian_composure −0.1`。
- 本拍结束时，Mia 在里面喊："Are you two coming back in?"（跟随规则）

**本地 mix-in**：
- 你说那是 Leo 的车（`mention_car`）→ "Lots of yellow cars in this city." 烟灰弹得太快。`revealed += car_downstairs`，`julian_composure −0.15`。
- 你问他为什么一直穿着外套（`ask` + 物件 jacket）→ "We cancelled the heating already." 屋里传来 Mia 的声音："No we didn't."
- 你问工作室、钱（`ask_about_move` + 话题 money）→ "The studio's fine. The studio's great." 说了两遍。话题 money 升到第 2 层。

**效果**：`tension +0.5`。
**插图**：#5 阳台上，Julian 的烟头，楼下的车。

### 6. `two_afternoons` · 两个下午（中点危机）

主干 · 第二阶段 · 斜率 +2 · 1.5 分钟 · 最多 3 回合

**前提**：`mia_in_the_kitchen` 和 `julian_on_the_balcony` 都演过（或者其中一个演过，且剧情分钟 ≥ 9）；三人都在客厅。
**意图**：两人当着你的面，说出了两个对不上的下午。场面爆掉。注意：Mia 绝不说下午的具体时间，Julian 绝不说 afternoon 这个词。

**步**：
1. 话头从搬家来：Julian 跟你抱怨打包："We packed all day. Together. Didn't leave the flat once." 几乎同时，Mia 说："I was lying down. I had a headache. I didn't see anything." 两人都停住了。
2. 拌嘴升级，句句暗指下午。Julian："You always make me clean up your mess." Mia："I cleaned up yours." 一只杯子在木箱上晃了一下，Mia 一把扶住。
3. 两人同时转向你。Julian："{name}, tell her she's remembering it wrong." Mia："Tell him."
   → 问你（两人都在问；沉默算两人都输）

**结尾**：
- Julian 赢：Mia 放下抹布，去了厨房。`side −1`。
- Mia 赢：Julian 拿起烟去了阳台。`side +1`。
- 沉默：两人都安静下来。Julian 给每个人倒酒："Let's not do this tonight." `couple_unity −1`。

**本地 mix-in**：
- 你问下午有没有人来过（`ask_about_afternoon`）→ 两人同时说："No." 太快了。`julian_composure −0.1`，`mia_composure −0.1`。
- 你问"什么事都没看见"是什么意思（`ask` + 话题 afternoon，问 Mia）→ Mia："Nothing. It's a thing people say." `mia_composure −0.15`。

**效果**：`tension +1`；话题 afternoon 升到第 2 层；`couple_unity −1`（两人吵起来本身就伤）。
**插图**：#8 两个下午：两人隔着木箱对峙。

### 7. `noras_call` · Nora 的电话

主干（必接）· 第二阶段 · 斜率 +1 · 1 分钟 · 最多 3 回合

**前提**：你接了 Nora 的电话（`nora_call == answered`）。
**地点**：你在哪就在哪。和你同一个房间的主人能听到你这边说的话。
**意图**：Nora 只有声音。急，说话直。她问 Leo 是不是和你在一起。你在电话里说的话，是你第一次回答 Nora。

**步**：
1. Nora："Hey. Sorry. Is Leo with you? He said he'd be at Julian's with you tonight. He's not picking up." 同一个房间里的主人都安静了。
2. Nora 追问："Did he say anything to you today? Anything weird?"
   → 问你（不是站队问题，你的回答写进 `nora_told`，规则见下）
3. Nora："Okay. Okay. If you hear from him, call me." 挂断。同一个房间里的 Julian："Who was that?"

**`nora_told` 怎么判**：
- 你说出任何一条已揭露的事实，或者 `claims` 里的事实（Leo 来过、车在楼下、语音、手机在 Julian 外套里）→ truth；
- 你说 Leo 没来、一切正常 → lie；
- 其他情况 → none。
- 以后每次回答 Nora 都会覆盖这个值，`testimony` 的回答是最终值。

**本地 mix-in**：
- 你把手机递给主人（动作：phone give）→ Julian 摇头；Mia 往后退了一步。
- 你直接说 Leo 的车在楼下（`mention_car`，对 Nora 说）→ Nora："What? Then where is he?" `nora_told = truth`；如果主人在场：`julian_composure −0.2`，`mia_composure −0.2`。

**效果**：`tension +0.5`。挂断后 Nora 去打 Leo 的电话 → `leo_phone = buzzed` → 必接拍 `the_buzz`。

### 8. `the_buzz` · 手机在震

主干（必接）· 不限阶段 · 斜率 +2 · 1 分钟 · 最多 2 回合

**前提**：Julian 外套里 Leo 的手机震了（`leo_phone == buzzed`）。可能是你打了 Leo 的电话（第一分钟打也算），也可能是 Nora 在打。
**意图**：外套里亮起了光。Julian 找借口离开房间；Mia 盯着那件外套。

**步**：
1. 嗡嗡的震动声，从 Julian 的外套里传出来。Julian 的手按上口袋，屏幕的光透过布料亮了一下。
2. Julian 站起来："Work. Sorry. Australia's awake." 他去了阳台。Mia 盯着他的背影，又转过来看你："He has two phones now. For the move." → 钩子：Mia 等你说点什么。

**本地 mix-in**：
- 你问那是谁的电话、要看看（`ask`，对 Julian）→ "Nobody you know." `julian_composure −0.15`。
- 你又打了一次 Leo 的电话（动作：phone call leo）→ 外套又震了。Julian 停下，没有回头。`revealed += leo_was_here`，`julian_composure −0.2`。
- 你伸手去掏他的外套（动作：jacket search）→ Julian 在场且 `julian_composure ≥ 0.3` 就拦住你，`julian_composure −0.15`；没拦住 → `leo_phone = found`，`revealed += leo_was_here`，`the_admission` 优先级最高。

**效果**：`tension +1`；`julian_composure −0.15`。
**插图**：#7 Julian 外套口袋里亮起的光。

### 9. `dont_go_yet` · 别走

卫星（必接）· 第二阶段起 · 斜率 +1 · 1 分钟 · 最多 2 回合

**前提**：你想离开公寓，被 Mia 拦在了门口（第二阶段起 Mia 在场，且 `mia_composure ≥ 0.3`；interaction-design.md §6.6）。
**意图**：Mia 背靠着门求你留下；Julian 反而帮你拿外套，他希望你作为"一切正常"的证人离开。

**步**：
1. Mia 背靠着门："Stay. Please. Just till dessert." 她的手在抖。Julian 已经拿着你的外套过来了："Mia. Let them go. It's late."
2. → 问你：留下，还是走（两人都在问；沉默算留下）

**结尾**：
- 留下（Mia 赢）："Thank you." 三人回到客厅。`side +1`。
- 坚持要走（Julian 赢）：Mia 让开了。你得在下一回合再写一次"离开"才会真的走（被拦过一次以后 Mia 的镇定值更低，可能就拦不住了）。`side −1`。
- 如果你已经知道 Leo 死了：Julian 不再帮你拿外套。Mia："If you walk out that door, you're going to the police. Aren't you." Julian："Sit down, {name}." 这时你的回答不改 `side`，`tension +0.5`。

**效果**：`tension +0.5`；被拦这一下 `mia_composure −0.15`（规则自带）。

---

## 3. 第三阶段：摊牌

### 10. `the_admission` · 他没走

主干 · 第三阶段（触发了可以更早）· 斜率 +2 · 1.5 分钟 · 最多 3 回合 · 长段落

**前提**：下面任意一条成立。
- a. 箱子被打开（必接）；
- b. `mia_composure < 0.3`；
- c. Leo 的手机被你找到（`leo_phone == found`，优先级最高）；
- d. `the_buzz` 演过，你当面指控（`accuse_julian` 或 `accuse_mia`），且 `player_suspicion ≥ 2`（优先级高）；
- e. `revealed` 里有 `missed_call` 和 `car_downstairs`，你拿语音和车去对质（`mention_voicemail` 或 `mention_car`，优先级高）；
- f. `downstairs` 演过，且 `mia_composure < 0.6`。

**意图**：第一次承认 Leo 死了。由更不镇定的那个人说出口；T2 下通常是 Mia。

**步**：
1. 说出口的那个人看向木箱。
   - Mia 版："He's not late." 停了很久。"He's here. He's been here the whole time."
   - Julian 版："He came by. Earlier. He's not leaving, {name}." 他还是不说 dead，也不说 body。
   - 开箱触发版：螺丝落在地板上。桌布滑下来。你看见了一只鞋。
2. 另一个人想把话收回来。Julian："Mia. Stop." 或者 Mia："Julian, don't."
3. 事实摆在桌上：Leo 死了，在箱子里。两人都看着你。→ 钩子：等你的反应。

**本地 mix-in**：
- 你说要报警（`threaten_to_tell`）→ Julian："Wait. Just wait. Let us explain." （真的拨号是动作，Julian 在场且镇定值够就会拦。）
- 你转身要走（动作：leave）→ Mia 拦住你，接必接拍 `dont_go_yet`。
- 你问"怎么死的"（`ask_about_afternoon`）→ 留给 `the_versions`：Julian："Sit down. I'll tell you. I'll tell you everything."

**效果**：`tension +1`；`revealed += leo_was_here, leo_dead, body_in_crate`；说出口的人镇定值 −0.2。
**插图**：开箱触发时，画面停在那只鞋。

### 11. `the_versions` · 两个版本

主干 · 第三阶段 · 斜率 +1 · 1.5 分钟 · 最多 3 回合

**前提**：`the_admission` 演过。
**意图**：竹林中，各说各的。T2 下，Julian 抢先顶罪，Mia 说她不记得了。

**步**：
1. Julian 抢先说，像背过一样："He came for money. We argued. He grabbed me, I pushed him, he hit the counter. That's it. That's all it was."
2. 你看向 Mia。Mia："I don't... I don't remember. I was in the hall. I heard it." Julian 看着她，点头点得太用力。
3. Julian："That's what happened, {name}."
   → 问你：你信不信这个版本（提问的人：Julian；沉默算接受）

**结尾**：
- 接受：Julian 松了一口气，给每个人倒酒。`side −0.5`，`couple_unity +1`。
- 怀疑：Julian 的手停在酒瓶上。Mia 开始发抖。`julian_composure −0.2`，`mia_composure −0.2`。

**本地 mix-in**：
- 你问为什么不叫救护车（`ask`）→ Mia："He wasn't breathing. He wasn't..." Julian："Mia." `mia_composure −0.2`。
- 你直接问 Mia 是不是她（`accuse_mia`）：
  - `mia_composure < 0.2` → Mia："I hit him. With the bottle. He had his hands on Julian's throat." `revealed += who_struck`。
  - 否则 → Mia 摇头；Julian 挡在你们中间："Leave her out of it."
- 你问钱（话题 money）→ Julian："The studio money. He found out. He wanted his share." `revealed += embezzlement`。

**效果**：`tension +0.5`；`revealed += leo_wanted_money`。

### 12. `the_offer` · 交易

主干 · 第三阶段 · 斜率 +1 · 1.5 分钟 · 最多 3 回合

**前提**：`the_versions` 演过。
**意图**：Julian 要你当证人：今晚只是一顿饭，Leo 没来。他可以给钱，不然就威胁你。Mia 用另一种方式求你：她想有一个人知道真相，同时不毁掉她。

**步**：
1. Julian 平静下来，近乎温柔，给你倒酒："Here's what happens. Six o'clock the movers come. Seven forty we're gone. Tonight was dinner. He never showed."
2. 筹码："There's money. More than you'd think. The studio money." `revealed += embezzlement`。
   - 威胁，如果 Julian 知道你有未接来电（`heard_by` 里有他）："Two missed calls from him, and you just happened to walk in at seven? Who do you think they'll believe?"
   - 否则："You were here all night, {name}. You ate off that crate."
3. Mia："Please. Don't make it worse. For him. For me."
   → 问你（两人都在问；沉默算还在犹豫）

**结尾**：
- 接受（`promise_silence`）：Julian 跟你碰杯。Mia 转过脸去。`side −1`，`couple_unity +1`。
- 拒绝（`threaten_to_tell`）：两人第一次站到了一起，看着你。`couple_unity +1`，`julian_composure −0.2`。如果你这时和 Julian 单独在一起，可能接 `second_crate`。
- 犹豫或沉默：Julian："Take your time. You've got till six."

**本地 mix-in**：
- 你问多少钱（`ask`）→ Julian 说了一个数。Mia："Julian."
- 你提到 Nora（话题 leo）→ Julian："Nora doesn't need to know anything."

**效果**：`tension +0.5`。

### 13. `downstairs` · 楼下

主干（必接，剧情第 13 分钟）· 斜率 +2 · 1 分钟 · 最多 2 回合

**前提**：剧情时钟跨过 13 分钟（Nora 第 3 级）。
**意图**：Nora 的短信。你的手机亮了，主人们看见了你的脸色。

**步**：
1. 你的手机震动。Nora："I'm downstairs. His car is here. His location says he's in your building." 短信同时出现在你的手机里。
2. 主人们的反应：
   - 还没承认：Mia 看向窗户。Julian："Who's texting you, {name}?"
   - 已经承认：Mia："She's here? She's here." Julian："Don't answer it."
   → 钩子：你怎么回 Nora。

**本地 mix-in**：
- 你回短信说了真话（动作：phone text nora，内容含事实）→ `nora_told = truth`。用的是你自己的手机，没人拦得住；Julian 看着你打字。
- 你回短信撒谎（内容是"他不在""没来"）→ `nora_told = lie`。
- 你走到窗边往下看（动作：window look）→ 楼下有个人站在那辆黄色车旁边，仰头看着这栋楼。

**效果**：`tension +1`；`nora_pressure = 3`；`revealed += car_downstairs`；`mia_composure −0.2`（她最怕的就是 Leo 的妹妹；这可能触发 `the_admission` 的条件 f）。

### 14. `the_knock` · 敲门

主干（必接，剧情第 16 分钟，或第 40 回合）· 斜率 +2 · 1 分钟 · 最多 1 回合

**前提**：剧情时钟跨过 16 分钟，或者到了第 40 回合。
**意图**：敲门声。Nora 进门。三人戏开始。

**步**：
1. 敲门声。屋里三个人都看着门。没人动。敲门声又响了一次。
2. Julian 去开门。Nora 进来，外套是湿的，手里攥着手机。她看见木箱上的晚饭和杯子："Where is he? His car's downstairs. His phone's in this building." → 钩子：直接接 `testimony` 的开场，写进同一段文字。

**效果**：`tension +1`；`nora_pressure = 4`；Nora 在客厅。
**插图**：#9 门口的 Nora。

### 15. `testimony` · 证词

主干 · 第三阶段 · 斜率 +1 · 1 分钟 · 最多 4 回合

**前提**：`the_knock` 演过；Nora 在场。
**意图**：你说的每一句话都是证词。Nora 问的是你，主人们在她身后。

**步**：
1. Nora 只看着你："{name}. You've been here all night. Did he come?" Julian 站在她身后，Mia 站在厨房门口。
   → 问你（不是站队问题；回答按 `noras_call` 里的规则写进 `nora_told`，这次是最终值；沉默见下）
2. 按你的回答：
   - 撒谎，替主人说话："He never showed." → Julian 接上："Told you. Classic Leo." Nora 看着你看了很久。
   - 说真话，或者看向木箱（看向木箱也算 truth）→ Nora 转向木箱。Julian："Nora. Wait."
   - 沉默或回避 → Nora 转向最怕她的那个人："Mia?"
3. 收束，进入结局判定（§4 开头）。

**本地 mix-in**：
- 你说 Leo 来过，但不说他在哪（`claims` 含 leo_was_here）→ Nora："When? Where is he now?" 再问一回合。
- 你对 Julian 或 Mia 说话，不理 Nora（addressee 不是 Nora）→ Nora："I'm talking to you, {name}."

**效果**：`tension +0.5`；`nora_told` 定稿。

---

## 4. 结局

**判定顺序**：
- 任何时候都先看 `second_crate`；
- 你离开了公寓（没被拦住）→ 直接进 `bon_voyage`；
- `testimony` 收束后，按下表从上往下取第一个成立的。

| 顺序 | 结局 | 条件 |
|---|---|---|
| 1 | `confession` | 有人的镇定值 < 0.15，而且你站在他那边（Mia：`side ≥ +1`；Julian：`side ≤ −1`），且 `nora_told != lie` |
| 2 | `open_it` | `nora_told == truth`，或者你报警打通了（`police_called`） |
| 3 | `the_witness` | `revealed` 里有 `leo_dead`，且 `nora_told` 是 lie 或 none |
| 4 | `bon_voyage` | 其他情况（你到最后都不知道真相） |

### 16. `bon_voyage` · 送别

**两种进入方式**：
- A. 你提前离开公寓，没被拦住；
- B. 判定兜底：你到最后都不知道真相。

**步**：
1. A 版：你下楼，经过那辆黄色的车，挡风玻璃上夹着一张罚单。B 版：Julian 和 Mia 对 Nora 说"他根本没来"，你在旁边。Nora 看了你一眼，走了。
2. 尾声：清晨六点，搬家工人抬起木箱。"Heavy one."

**插图**：#10 结局。

### 17. `the_witness` · 证人

**条件**：见判定表第 3 行。
**步**：
1. Nora 走了，门在她身后关上。Julian 收拾桌布，Mia 没动。
2. 尾声：07:40，两人登机。你的手机亮了：Nora。你没有点开。

**插图**：#11 结局。

### 18. `open_it` · 开箱

**条件**：`nora_told == truth`，或者你报警打通了。报警版由警察开箱，第 1 步换成楼下的警笛和敲门声。
**步**：
1. Nora 从玄关的 TOOLS 箱里拿出电钻；如果箱子已经开了，就跳过这一步。螺丝一颗一颗落在地板上。
2. 桌布滑下来。一只鞋。Nora 没出声。
3. Julian 把罪揽到自己身上："It was me. I did it."
   - `couple_unity ≥ 2`：他顶到底。
   - `couple_unity < 2`（比如他已经知道是 Mia 叫的 Leo）：他不再护着她："Ask her. Ask her what she did with the bottle."
   - Mia 会不会自己承认，看 `side` 和她的镇定值：你站在她那边且她的镇定值 < 0.3 时，她会说："I hit him. He had his hands on Julian's throat."
4. 尾声：远处有警笛。Nora 坐在地上，背靠着木箱。

**插图**：#12 结局。描写停在那只鞋。

### 19. `confession` · 自首

**条件**：见判定表第 1 行。对应 Façade 的最好结局。
**步**：
1. 最不镇定的那个人，自己对 Nora 说出来。
   - Mia 版是真话："It was me. I hit him. I'm sorry. I'm so sorry."
   - Julian 版是假的，他还在替 Mia 顶罪："I did it, Nora. Me." 反讽在于你知道（或者猜到）不是他。
2. 另一个人没有拦。
3. 尾声：没人再说话。Nora 坐在木箱旁边。楼下那辆车还在。

**插图**：#13 结局。

### 20. `second_crate` · 第二只箱子

**条件**：任何时候都可以触发，但只在 Nora 进门之前。
- 你和 Julian 单独在一起（同一个房间，Mia 不在）；
- `julian_composure < 0.15`；
- `side ≥ +1.5`（强烈反他）；
- 这一回合你威胁要说出去（`threaten_to_tell`）。

**步**：
1. Julian 不笑了。他把阳台门拉上，或者把客厅的门关上，锁舌响了一声："Sit down, {name}."
2. 结束在他叫你名字的那一下。只暗示，不描写。

**插图**：#14 结局。

---

## 5. 写的过程中定下的规则（2026-10-06 已定）

| # | 规则 | 同步到 |
|---|---|---|
| 1 | **张力换算**：效果里的 `tension` = 斜率 × 0.5，story.md §9 的斜率列不变。v0 没有降温的拍，story.md §6.2 第 10–12 分钟的回落要等 `the_quiet`、`college_days`、`the_long_drive` 这些卫星拍补上 | story.md §9 |
| 2 | **来电那一回合不选新拍**：正文停在手机响上；下一回合看你接不接，接了进 `noras_call`，不接 Nora 就去打 Leo 的电话，进 `the_buzz` | interaction-design.md §7.3、story.md §7.1 |
| 3 | **空档快进**：没有作者写的拍可演、又有时钟事件在等着时，把时钟直接快进到下一个事件，正文写"好一阵没人说话"。没有时钟事件在等时，才交给 `GENERATE_NEW` | interaction-design.md §7.2、plan.md M2 / M3 |
| 4 | **中止的拍可以再进**：引擎把"中止的拍"和"演过的拍"分开记，中止的可以再选。比如拒绝了 Mia 的邀请，之后自己走进厨房，还能从"你主动来"的开场进入 `mia_in_the_kitchen` | interaction-design.md §6.2、plan.md M3 |
| 5 | **`the_buzz` 的揭露**：你自己再打一次 Leo 的电话、Julian 的外套又震了，直接揭露 `leo_was_here` | 本文 §2 第 8 拍 |
| 6 | **新动作**：搜 Julian 的外套（Julian 阻拦）、看窗外、把手机递给别人、回短信（按内容判真话还是谎话） | interaction-design.md §3.6、plan.md M1 |
| 7 | **`two_afternoons` 的写法**：Julian 说两人一整天在一起打包；Mia 说她头疼躺着，"什么都没看见" | 本文 §2 第 6 拍 |
| 8 | **`confession` 的反讽**：Julian 先崩溃时，他的"自首"是假的，还在替 Mia 顶罪 | story.md §10 |
