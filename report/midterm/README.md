# 中期报告（CSCI 566 Project Midterm Report）

**截止：2026-11-15（周日）23:59 PT，Gradescope 小组提交，一个人交一份 PDF，并把全部队友加进这份提交。**
要求四部分：Progress so far、Literature review、Initial results、Updated plan；推荐 5 到 6 页（不含参考文献），模板可选。

| 文件 | 内容 |
|---|---|
| `main.tex`、`refs.bib` | 报告源文件（NeurIPS 2026 单栏模板，`preprint` 选项） |
| `neurips_2026.sty` | 官方模板的样式文件，原样放入 |
| `main.pdf` | 当前编译结果（8 页，正文约 5.8 页，参考文献从第 6 页下半起） |
| `data/selfplay_stats.json` | 表 2、表 3 和正文里自博弈数字的来源（11 局旧代码 + 2 局新代码的汇总） |
| `data/tension_bins.json` | 图 2 的数据（按剧情分钟分段：实测、beat 自报、目标） |

## 编译

```bash
cd report/midterm
tectonic main.tex          # 自动处理 BibTeX 和多遍编译；第一次会下载宏包
```

也可以把 `main.tex`、`refs.bib`、`neurips_2026.sty` 三个文件传到 Overleaf（编译器选 pdfLaTeX）。

## 还缺什么（PDF 里红色的 TODO，提交前必须全部清掉；作者名单已填：Group 26 的 6 位成员）

1. **表 5（输入理解 M2）**：整张表的数字由 M2 的负责人（据 commit 和 CARC 路径推断是 Amon / Haosen Cao，请确认）从 CARC 上的实验结果填。需要：每个 rung 在冻结测试集 `test_v1` 上的各输出头指标、老师自一致性（上限）、训练和测试各有多少局多少回合。
2. **M2 一节里的那句观察**（turn 级输出头只读 [CLS] 时落后于冻结句向量基线）：这句来自 M2 负责人的 commit 说明，没有数字，请他确认或删掉。

## 请队友重点核对

- **每个数字**：正文里的自博弈数字都来自 `data/selfplay_stats.json`；规则对 LLM 的小评测来自 `backend/prompts/evals/results/summary.md`（2026-10-12）。
- **第 5 节计划的日期和分工**：我按剩余时间排的目标，需要全组确认能不能做到。
- **研究问题 RQ1–RQ4 的措辞**：是否与 pre-proposal 一致。
- **文献综述**：引用的每一条都经过一手来源核对（出版方、ACL Anthology、NeurIPS 官网、Crossref 或论文第一页），但**写进报告的每篇论文，负责这一节的人都应该自己读过**。`refs.bib` 开头注明了哪些字段因为核实不了而特意没写。
- **没有做的事**：没有训练好的 M1，没有人工标注，M2 结果还没有；报告里是如实写的，不要在评审后改成别的说法。
