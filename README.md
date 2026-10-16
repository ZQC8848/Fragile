# Fragile（易碎品）

一部回合制的互动悬疑剧。你是一对夫妻的大学老友，来参加他们移民前夜的告别晚宴，饭就摆在一只拧死了螺丝的海运木箱上。被邀请的 Leo 没有来。每回合你写下自己说什么、做什么，系统用第一人称写出接下来发生的事。

背后是一个可以训练的 Drama Manager：LLM 负责写正文和理解输入，决定剧情走向的四个模块（M1 打分、M2 理解输入、M3 一致性检查、M4 张力估计）都有规则、LLM、训练三条路径，可以切换，也可以影子运行。这是 USC CSCI 566 的课程项目。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/` | FastAPI 服务、回合引擎、beat 池与剧本数据、各角色的 prompt、测试 |
| `frontend/` | React 前端：玩家界面 `/play` 和开发者后台 `/console` |
| `schemas/` | 前后端共享的 JSON Schema：消息协议、状态、beat、数据文件 |
| `art/` | 风格基准、角色设定图、卡片肖像、关键画面、公寓平面图（Git LFS） |
| `story.md` | 故事、人物、真相、结局 |
| `interaction-design.md` | 玩家怎么输入、系统怎么回应、界面怎么排 |
| `backend-design.md` | 系统结构、四个模块、数据与训练 |
| `beat-script.md` | 20 个 beat 的剧本 |
| `plan.md` | 开发计划、里程碑进度和实现中定下的细化（R1–R26） |

## 准备

需要 Python 3.13 和 [uv](https://docs.astral.sh/uv/)、Node.js 20 以上、git-lfs。

```bash
git lfs install
git clone git@github.com:ZQC8848/Fragile.git
cd Fragile
git lfs pull                      # 拉取 art/ 下的图片
cp backend/.env.example backend/.env
```

`backend/.env` 是唯一存放 API key 的地方，已被 gitignore，不要提交。不填任何东西也能运行：所有 LLM 角色默认用**离线 mock**，确定、不联网、不花钱，正文是剧本里写好的文字拼起来的，读起来像舞台说明。要用真实模型，按 `.env.example` 里的说明给各角色配置供应商、模型和 key，再把角色名写进 `LLM_LIVE_ROLES`（例如 `review,narrator,guard`），或者在 Console 里逐个切换成 live。

## 启动

开两个终端：

```bash
# 后端：http://localhost:8000
cd backend
uv sync
uv run uvicorn app.main:app --port 8000
```

```bash
# 前端：http://localhost:5173
cd frontend
npm install
npm run dev
```

前端开发服务器会把 `/api`、`/ws` 和 `/art` 转发到 8000 端口，所以后端要先起来。浏览器打开：

- **http://localhost:5173/play**：玩家界面
- **http://localhost:5173/console**：开发者后台

在 VS Code 或 Claude Code 里，也可以直接用 `.claude/launch.json` 里的 `backend` 和 `frontend` 两个配置启动。

## 玩家界面 `/play`

开局依次是标题、前情提要、四张人物卡、选择你的卡片并输入名字。进门之后：

- 在输入框里写一句话，引号里的是你说的话，其余是动作和神态，回车发送。系统先把它拆成"说 / 做 / 神态 / 对谁"的草稿，你可以改，再回车才算真正走一回合。替别人做决定、替自己决定结果的句子会被拒绝，不耗回合，并给出一键改写的建议。
- 也可以切换成分栏直接填，或者点 "Suggest moves" 从三个建议动作里选。
- 顶部的 Map、Phone、People 三个按钮分别打开公寓平面图、手机和人物卡，点外面就收起。在地图上点一个房间，会把"往那边走"填进输入框。
- 结局之后可以查看 "What really happened"：真相只在会话结束后才由后端提供。

用真实模型时，一回合通常要 30 秒到 2 分钟，等待时界面只显示一个安静的 "…"。

## Console `/console`

Console 是给开发和调试用的后台，能看到**全部**状态，包括所有秘密，不要给玩家看。

1. **选会话**：顶部下拉框列出这个后端进程里的所有会话（每 5 秒刷新），从玩家界面开始的会话也在里面。也可以点 "New test session" 直接开一局，不用走开局流程。Console 和玩家界面可以同时连着同一局，互不影响；玩家界面的连接收不到状态和回合记录。
2. **中栏：回合检查器**。每回合一行，显示输入、所在 beat、guard 重写或兜底情况、总耗时。点开一行能看到这一回合的完整链路：输入和审核、M2 拆出的单元、世界规则的结果、反应候选和选中项、beat 进度和时钟、DM 的候选 beat 和概率、叙述者的每个片段、guard 的判定、状态变化、各阶段延迟和每一次 LLM 调用。
3. **右栏：全局视图**。关键状态值（站队、两人的镇定值、夫妻同盟、对 Nora 说了什么、各人所在房间、已揭露的事实），张力曲线（目标曲线、beat 自报的张力、M4 实测的张力，可切换成表格），历次决策，以及拍子架（每个 beat 现在能不能选、为什么不能）。
4. **左栏：控制**。
   - Scorer：A 规则，B LLM，C 训练模型（目前委托给 LLM）。
   - Tau：DM 选 beat 时的温度。
   - Force a beat next：强制下一拍演指定的 beat。
   - Jump clock：把剧情时钟跳到指定分钟，途中的时钟事件（Nora 的短信、电话）会依次触发。
   - State patch：直接改状态，例如 `{"mia_composure": 0.2}`。
   - Reset session：清空这一局。
   - LLM roles：每个角色单独在 mock 和 live 之间切换，只有在 `backend/.env` 里配置了 key 的角色才能切到 live。

## 终端客户端

不开浏览器也能玩，用的是同一个回合引擎：

```bash
cd backend
uv run python tools/play_cli.py --name Sam --gender female      # 全部离线 mock
uv run python tools/play_cli.py --live all                       # 全部角色用 .env 里配置的真实模型
```

游戏中可用 `/phone`、`/card`、`/options`、`/state`、`/trace`，`/help` 列出全部命令。

## 测试与检查

```bash
cd backend
uv run pytest                                    # 离线 mock 下的全部测试
uv run ruff check .
uv run python tools/eval_prompts.py --offline    # prompt 评测集，规则路径；去掉 --offline 用真实模型

cd frontend
npm run lint                                     # eslint 和类型检查
npm run build
npm run gen:types                                # 改了 schemas/messages_v2.json 之后重新生成前端协议类型
```

## 日志

每一局的回合记录和决策记录写在 `backend/data/logs/<session>/`（已被 gitignore），GENERATE_NEW 现场生成的 beat 写在 `backend/data/candidate_pool/`，等人工审核。
