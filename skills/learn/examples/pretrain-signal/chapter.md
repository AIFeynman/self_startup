> **本章目标**：第 1 轮「看懂」的主干机制章。把预训练里三个"信号与算力"问题讲到能自己推：①数据受限时算力怎么分（参数、重复轮数、合成数据、RL 算力）；②mid-training 该注入什么数据才能让后面的 RL"学得动"；③Muon 为什么是那个更新式、FP8/FP4 为什么能训、会在哪里炸。
> **学完能回答**：① Chinchilla 的最优条件怎么推出来，数据受限时哪一项开始失效、为什么要换成 Practical Scaling Laws 的饱和形式？② RL 的 sigmoid 曲线里 A、C_mid、B 分别管什么，哪些设计只改效率、哪些改上限？③ Muon 的更新式为什么是 $UV^\top$ ，Newton–Schulz 的五次多项式怎么把奇异值推向 1，DeepSeek-V4 为什么最后两步换系数？④ 「先调好基线」那篇论文把 Muon 的优势从 1.52× 压到了多少，剩下的是真的吗？⑤ FP4 训练最难稳定的是哪一环，Dense 与 MoE 的 FP4 RL 各卡在哪？
> **预计用时**：150–180 分钟。建议备纸笔，三个手算例子先自己算再看答案。
> **前置**：交叉熵、梯度下降、矩阵 SVD 的概念（$G=U\Sigma V^\top$ ）。结构侧的 N（参数量）由「预训练·结构：长、宽、深怎么设计」决定；本章只把它当作一个数。

## 资料时效

- **主读物全部在近 6 个月内**（今天是 2026-11-08）：Practical Scaling Laws（2026-05-09）、DeepSeek-V4 报告（2026-04-26）、数据受限三篇（2026-06 至 10）、mid-training 三四篇（2026-09 至 10）、Muon 反思两篇与 FP4 RL（2026-11-02/03，距今一周）。
- **我联网又查了一遍**（标准检索「Muon vs AdamW 2026-11」）：没有找到比上面两篇 11-02 论文更新的结果；能搜到的 Muon 对比（如 Essential AI 的 *Practical Efficiency of Muon for Pretraining*，2025-05）都早于它们，属于被它们复核的一方。**这意味着本章最新的结论只有预印本级证据**：规模为 1.9M–15M 活跃参数的小梯子、单实验室、未经同行评审，后面每次引用都会标出来。
- **结论**：仍可作为主读物，但「Muon 到底赢多少」「FP4 RL 的 MoE 解法」两处是一周内的新结论，半年后大概率会被修正；经典锚点（ScaleRL 2025-10、Kimi K2 2025-07）不过时，因为后来的工作都在它们定义的坐标系里做事。
- 读法说明：ScaleRL、Practical Scaling Laws、两篇 Muon 反思、Stable FP4、MoE FP4 RL、DeepSeek-V4（Muon 与数据配置）、Qwen3-Coder-Next（mid-training 数据）我读了正文；其余 mid-training 论文（Nemotron 开源配方、TrajLong、Trajectory Soup、可学性理论）和 Kimi K3 只核读了摘要与表层数字，正文里会标「仅摘要」。

## 全景图

先看整条训练线上，这三个专题各管哪个"旋钮"：

<div class="dg-flow steps">
<div class="dg-node"><b>算力预算</b><span>FLOPs、GPU 时、推理成本</span><div class="dg-more">起点。第一个问题：算力怎么在参数 N、token 数 T、不重复数据 D、RL 之间分。这是「Scaling law」一节。</div></div>
<div class="dg-node hot"><b>预训练</b><span>优化器 + 精度</span><div class="dg-more">同样的数据，用 Muon 还是 AdamW、用 BF16 / FP8 / FP4，决定"每 FLOP 学到多少"和"会不会崩"。对应后两节。</div></div>
<div class="dg-node"><b>mid-training</b><span>长上下文 + 轨迹</span><div class="dg-more">在预训练和 RL 之间，把能力先验铺好。对应「数据与 mid-training」一节。</div></div>
<div class="dg-node"><b>RL 后训练</b><span>可学性 + 训推一致</span><div class="dg-more">RL 能学到多少取决于前面铺了什么，也取决于训练和 rollout 的数值是否一致（FP8/FP4 RL）。</div></div>
</div>

<div class="dg-tree">
<div class="dg-root"><b>预训练的"信号与算力"</b><span>同样的 FLOPs，怎样让模型学到更多、训得更稳、能被 RL 继续推？</span></div>
<div class="dg-branches">
<div class="dg-branch hot"><b>Scaling law 与分配</b><ul><li>Chinchilla：N 与 D 同比放大</li><li>数据受限：重复、正则、集成</li><li>RL 算力：sigmoid 曲线</li></ul></div>
<div class="dg-branch"><b>数据与 mid-training</b><ul><li>配比、合成改写</li><li>agentic 轨迹、长上下文</li><li>可学性：预训练决定 RL 上限</li></ul></div>
<div class="dg-branch hot"><b>优化器</b><ul><li>Muon：谱范数下最陡下降</li><li>MuonClip / 混合 NS</li><li>优势多少是调参假象</li></ul></div>
<div class="dg-branch warn"><b>低精度</b><ul><li>FP8 block scaling</li><li>FP4：转置一致、随机舍入</li><li>MoE 路由的训推失配</li></ul></div>
</div>
</div>

| 方向 | 核心问题 | 痛点 | 主流方案 | 热点（2026 下半年） | 开放问题 |
|---|---|---|---|---|---|
| Scaling law | 算力怎么分 | 好数据不够，Chinchilla 失效 | 过训练、多 epoch、统一饱和公式 | 数据受限 + RL 算力 | RL 曲线能否外推；合成数据算不算新数据 |
| 数据 / mid-training | 注入什么、何时注入 | RL 前模型没有 agent 先验 | 仓库、PR、轨迹混合 | 开源配方、轨迹合成 | 轨迹多样性、与 RL 环境匹配 |
| 优化器 | Muon 何时胜 AdamW | 收益被调参和数据规模混淆 | Muon + 权重衰减 + RMS 对齐 | 复核实验：优势缩水 | 小梯子结论能否到万亿级 |
| 低精度 | 数值稳定边界 | 4 bit 只有 8 个幅值 | 块缩放 + 随机舍入 + 对称恢复 | 端到端 FP4 RL | 低精度本身的 scaling 规律 |

## Scaling law 与算力分配

### 价值与动机

**一句话**：Scaling law 是把"这笔算力怎么花"变成一个可以求导的问题；2026 年它要回答的不再是"大还是小"，而是"没有新数据了，钱花在哪"。

<span class="judge">解读者判断</span> 先看一组可复算的数字。常用近似：训练算力 $C\approx 6ND$ （N 为参数量，D 为训练 token 数）。<span class="fact">源文事实</span> DeepSeek-V4-Flash 为 13B 激活参数、32T token，Pro 为 49B 激活、33T token（V4 报告 §2、§4）；Kimi K2 为 32B 激活、15.5T token。按"每个激活参数看多少 token"算：

- Flash：$32\times10^{12}/13\times10^{9}\approx 2462$ ，是 Chinchilla 经验值（约 20）的 123 倍。
- Pro：$33\times10^{12}/49\times10^{9}\approx 673$ ，约 34 倍。
- K2：$15.5\times10^{12}/32\times10^{9}\approx 484$ ，约 24 倍。
- 算力：Flash 约 $6\times13\times10^{9}\times32\times10^{12}\approx2.5\times10^{24}$ FLOPs（只算主项，忽略注意力项；以激活参数计，是 MoE 的通行口径）。

所有旗舰都在"过训练"。这不是工程师不懂 Chinchilla，而是目标函数变了：Chinchilla 最小化"给定训练算力下的 loss"，现实要最小化"训练 + 全生命周期推理的总成本下的质量"。

### 原理一：Chinchilla 的最优条件怎么推出来

**想法**：把 $D=C/(6N)$ 代入损失，对 N 求导，导数为零就是最优。

Chinchilla 的形式： $L(N,D)=E+\dfrac{A}{N^{\alpha}}+\dfrac{B}{D^{\beta}}$ 。其中 E 是不可约损失，A、B、α、β 是拟合常数。固定 C，令 $D=C/(6N)$ ：

$$L(N)=E+A N^{-\alpha}+B\left(\frac{6N}{C}\right)^{\beta}$$

对 N 求导并令其为 0：

$$-\alpha A N^{-\alpha-1}+\beta B\,6^{\beta}C^{-\beta}N^{\beta-1}=0\;\Longrightarrow\;\alpha\cdot\underbrace{A N^{-\alpha}}_{\text{参数项}}=\beta\cdot\underbrace{B D^{-\beta}}_{\text{数据项}}$$

第二步把 $B(6N/C)^\beta$ 写回 $BD^{-\beta}$ 。**直观含义**：最优点是"两项可约损失按各自指数加权后相等"。当 $\alpha\approx\beta$ 时两项相等，于是 N 与 D 同比例增长（$N^*\propto C^{\beta/(\alpha+\beta)}$ ），这就是"每个参数约 20 个 token"的来源。

它的前提藏在公式里：**$D$ 既是"看过的总 token"，又是"不重复的独立数据"**。只要数据管够、只训一个 epoch，这两件事等价；一旦数据有限，就拆成了两个量，公式随之失效。

### 原理二：数据受限时，Practical Scaling Laws 改了哪里

<span class="fact">源文事实</span> Practical Scaling Laws（2026-05-09）指出 Chinchilla 在数据受限区有三个结构性缺陷：独立数据变少时 loss 发散而不是饱和到"无信息基线"；无法表达容量超过数据后的过拟合；混淆了"看过的总样本"与"可用的独立样本"。它提出：

$$L(N,D,T)=E+(L_0-E)\frac{h}{1+h},\qquad h=\frac{a}{N^{\alpha}}+\frac{b}{T^{\beta}}+\frac{c\,N^{\gamma}}{D^{\delta}}$$

这里 T 是总训练样本数，D 是独立数据量，$L_0$ 是由损失类型决定的"完全没学到"的基线。三项分别是**欠容量**（N 太小）、**欠训练**（T 太少）、**过拟合**（N 相对 D 太大）。

**推导它为什么合理（两个极限）**：

1. h 很小时 $h/(1+h)\approx h$ ，于是 $L\approx E+(L_0-E)\left(\frac{a}{N^\alpha}+\frac{b}{T^\beta}\right)$ ，单 epoch 时 $T=D$ 且过拟合项可忽略，这正是 Chinchilla 的形状（A、B 吸收了 $L_0-E$ 的系数）。论文也明确写了"在数据充足、单 epoch 的极限下退化为 Chinchilla"。
2. h 很大时 $h/(1+h)\to1$ ，$L\to L_0$ ：loss **饱和在无信息基线**，不会像 Chinchilla 那样发散。

<details><summary>原文摘录 · arXiv 2605.09189 摘要</summary>

> We propose a closed-form extension, L(N, D, T) = E + (L_0 − E) h/(1+h) with h = a/N^α + b/T^β + c N^γ/D^δ, that decomposes loss into undercapacity, undertraining, and overfitting terms. It saturates between the irreducible loss E and an uninformed baseline L_0 fixed by the loss type, and reduces to Chinchilla in the data-rich, single-epoch limit.

</details>

**手算例子 1（改一个旋钮，看哪项被吃掉）**。取玩具参数（**假设**：三项在基准点分别为 0.10 / 0.15 / 0.05，指数都取 0.5，$E=2,\ L_0=10$ ，每次把一个量翻倍）。数字已用脚本核对：

| 操作 | 欠容量 | 欠训练 | 过拟合 | h | L |
|---|---|---|---|---|---|
| 基准 | 0.100 | 0.150 | 0.050 | 0.300 | 3.846 |
| N × 2（D 不变） | 0.071 | 0.150 | 0.071 | 0.291 | 3.805 |
| T × 2（同一数据多看一倍） | 0.100 | 0.106 | 0.050 | 0.256 | 3.631 |
| D × 2（新增独立数据） | 0.100 | 0.150 | 0.035 | 0.285 | 3.776 |

**检查**：只加参数，欠容量降了 0.029，过拟合项涨了 0.021，净收益只有 0.041（L 从 3.846 降到 3.805）；这就是"数据受限时加参数不划算"。**注意这是玩具**：这里 T×2 最划算是因为参数设定里欠训练项占比大，并不意味着"重复永远最好"，真实上限看下一节的实证。

<div class="dg-widget" data-src="widgets/data_constrained_h.html" data-height="400" data-title="拖动 N、T、D，看三项损失和总 L；对比 Chinchilla 式"></div>

![图1：Chinchilla（左）与 Practical Scaling Laws（右三列）的形状对比（原文 Fig.1）](figs/fig3.png)

> 图1 说明（原图，arXiv 2605.09189 v2）：上排横轴是参数量 N，每条线是一个固定算力 C，下排横轴是 FLOPs。最左列是 Chinchilla：N 越大 loss 单调下降到 E，永远没有"过大"的惩罚。右三列是新形式：低 D（独立数据少）时上排出现 **U 形**，存在一个最优 N*，过了之后 loss 反而变大，下排的平台 $E_\text{eff}$ 远高于 E；高 D 时曲线回到 Chinchilla 的样子。它支撑的论点：数据受限时存在"容量天花板"，算力再多也只是平台。

### 原理三：重复次数的收益上限

<span class="fact">源文事实</span> 三篇 2026 年论文各打一角：

- **重复次数随规模变**（2610.05126，2026-10-04）：在 Wikipedia 派生数据和 Proof-Pile-2 上，不同重复次数的排名随模型大小变；520M 的 Proof-Pile-2 实验里把重复从 16 降到 8，loss 更低且用的 token 更少。作者的实用做法：用小模型的 loss 曲线保留一个候选重复次数的短名单，在大模型上只评这几个（候选集在 PubMed、Caselaw 上于 200M 和 520M 都保住了最优点）。
- **正则与耦合 scaling**（2606.06888，2026-06-05）：提出 MIR（对随机掩码输入加一个辅助的下一词预测损失，叠在强权重衰减上，72M–1.4B 模型验证 loss 更低，1.4B 有下游收益），以及 SoftQ 这个把 N 与 D 耦合的 scaling law，认为 Chinchilla 的加性形式在重复数据区"设定错误"。
- **超参迁移 + 集成**（2610.37842，2026-10-27）：既有处方把权重衰减等超参随规模固定，且忽略集成，**以致 loss 可能随算力增加而变大**；作者拟合"超参随规模迁移的幂律"和"带集成的算力分配律"，在 FineWeb 的 100M token 上相对旧配方降验证 loss 超过 0.15 nats（困惑度降 14%），在最多 12× 更大算力上验证了拟合。

<span class="judge">解读者判断</span> 这三篇合起来的实操含义：数据受限时 **先调权重衰减和重复次数，再谈加参数**；而且"在小模型上调好的重复次数"不能直接搬到大模型（2610.05126），所以要用"小模型筛候选 + 大模型验证"。注意三篇的模型规模都在 1.4B 以下，上到旗舰规模是外推。

经典背景（本章未重读原文，来自库里的 2023 年论文）：[Scaling Data-Constrained Language Models](https://arxiv.org/abs/2305.16264)（Muennighoff 等）首次系统量化了"重复数据的价值衰减"。

### 原理四：RL 算力的 sigmoid 曲线

<span class="fact">源文事实</span> ScaleRL（2025-10-15，超过 40 万 GPU 小时）把 RL 的"算力—性能"拟合成 sigmoid：

$$R_C=R_0+\frac{A-R_0}{1+(C_\text{mid}/C)^{B}}$$

**逐项读**： $R_0$ 是 RL 开始前的奖励；A 是渐近上限；$C_\text{mid}$ 是拿到一半增益所需的算力（令 $C=C_\text{mid}$ ，分母为 2，$R=(A+R_0)/2$ ）；B 控制陡峭程度。

![图2：RL 缩放拟合式的各个参数（ScaleRL Fig.4 附近的示意）](figs/fig2.png)

> 图2 说明（原图，arXiv 2510.13786 html）：横轴是对数算力 C，纵轴是期望奖励。橙色星是训练点，蓝色实线是拟合，绿色叉是之后才跑出来的"扩展点"，虚线是外推。图中标出 A（顶部虚线）、$C_\text{mid}$（竖直黄线，增益的一半）与 B（控制斜率）。要点：**用前半段拟合，能预言后半段落在哪里**。

**手算例子 2（核对：用同一个公式把曲线算出来）**。取玩具参数 $R_0=0.40,\ A=0.65,\ C_\text{mid}=10$ （千 GPU 小时），$B=1.5$ ：

| C（千 GPU 小时） | 2.5 | 5 | 10 | 20 | 40 | 80 | 160 |
|---|---|---|---|---|---|---|---|
| $R_C$ | 0.428 | 0.465 | 0.525 | 0.585 | 0.622 | 0.639 | 0.646 |

**检查**：C=10 时恰好是 $(0.40+0.65)/2=0.525$ ；从 40 到 160，算力翻了四倍，奖励只涨 0.024。**拐点之后每翻一倍的收益是递减的**，所以关键不是"再跑多久"，而是"A 能不能抬高"。

![图3：ScaleRL 把单次 RL 外推到 10 万 GPU 小时（原文 Fig.1）](figs/fig1.png)

> 图3 说明（原图，arXiv 2510.13786）：横轴是 GPU 小时×10³（对数），纵轴是验证通过率（对数刻度）。蓝线为 ScaleRL-8B 稠密，橙线为 ScaleRL-17B×16 MoE。星号是训练点，叉号是后续真实跑出来的点，虚线是外推。约 16k GPU 小时之后的曲线预测，被其后的叉点基本命中（MoE 的叉点在约 0.70 上下，稠密约 0.62–0.64）。它支撑的论点：**稳定的配方遵循可预测的轨迹，可以用小规模跑出的前半段预测大规模**。

<span class="fact">源文事实</span> 作者的三个发现（摘要）：不同配方的渐近性能不同；损失聚合、归一化、课程、off-policy 算法这类细节主要改**效率**而不明显改渐近线；稳定配方可以从小规模外推。**给选型的含义**：评估一个 RL 技巧，要看它抬高了 A，还是只是把 $C_\text{mid}$ 往左移。

其他两篇补充：**2610.04158**（2026-10-03）解释了 RL 的 log-sigmoid / log-linear scaling 的理论来源，并把 Pass@1 上升与 Pass@N 下降这对矛盾归因于"策略选择的重新加权"；**2608.29296**（2026-08-29）给出大 batch 决策规则：大 batch 只有在吞吐增益超过它多付出的"达到目标所需样本数"代价时才缩短时间；GRPO/PPO 实验里，Adam 配合学习率按 √batch 缩放时，在一定 batch 范围内样本轨迹近似不变。

### 后续改进与同类对比

<div class="dg-timeline">
<div class="dg-event"><i>2022</i><b>Chinchilla</b><span>固定算力下 N 与 D 同比放大，约 20 token/参数</span></div>
<div class="dg-event"><i>2023</i><b>数据受限 scaling</b><span>量化重复 epoch 的价值衰减</span></div>
<div class="dg-event"><i>2025-10</i><b>ScaleRL</b><span>RL 算力用 sigmoid 拟合，区分上限与效率</span></div>
<div class="dg-event hot"><i>2026-05</i><b>Practical Scaling Laws</b><span>饱和形式：欠容量 / 欠训练 / 过拟合三项</span></div>
<div class="dg-event"><i>2026-06 至 10</i><b>SoftQ / MIR、重复次数、超参迁移+集成</b><span>把重复、正则、集成纳入处方</span></div>
</div>

| 方案 | 核心做法 | 代价 | 适用场景 | 代表 |
|---|---|---|---|---|
| Chinchilla 计算最优 | N、D 同比放大 | 假设数据管够 | 数据充足、不计推理成本 | 2022 |
| 过训练 | 小 N、大 D | 训练贵 | 推理流量大 | DeepSeek-V4、Kimi K2 |
| 多 epoch + 强正则 | 重复数据 + 权重衰减 / MIR | 需调重复次数 | 高质量数据用完 | 2606.06888 |
| 超参迁移 + 集成 | 随规模迁移超参，多模型集成 | 推理或训练多份 | 小数据、算力宽裕 | 2610.37842 |
| RL 算力外推 | 拟合 sigmoid，看 A 与 $C_\text{mid}$ | 需要先跑一段 | 决定要不要继续 RL | ScaleRL |

**选型判断**：数据没见底就按过训练走，数据见底就先调重复与正则，再考虑集成；RL 阶段先拟合曲线，看你的瓶颈在 A 还是 $C_\text{mid}$ 。

**推理感知**（我的推导，非论文）：总成本约 $6ND+2N\,D_\text{inf}=2N(3D+D_\text{inf})$ ，当服务的 token 数 $D_\text{inf}$ 超过训练 token 的 3 倍，就应该缩小 N、加大 D。这是"全旗舰过训练"的算术来源，忽略了 KV 缓存与硬件利用率差异。

### 难点、开放问题与常见误区

- **开放问题**：RL 曲线能否外推到更大算力（图3 只证到 10 万 GPU 小时）；合成改写数据算不算公式里的 D（还没有共识）；MoE 稀疏度与数据量的联合最优（本章资料里没有一手论文，计划里提到的 MOSAIC **待核实**）；Kimi K3 摘要称相对 K2 获得约 2.5× 的整体 scaling 效率提升，但这是 KDA、Attention Residuals、LatentMoE 和数据配方的合力，仅摘要、无法拆出各自贡献。
- **常见误区**：①「Chinchilla 比例仍是最优」：只在数据充足 + 不计推理成本时成立。②「重复次数在小模型上调好，大模型直接用」：2610.05126 显示排名随规模变。③「RL 多跑就会更好」：拐点之后每翻倍收益递减，要看 A。

<div class="dg-flash"><div class="dg-q">你的数据只剩 200B 独立 token，算力预算翻 4 倍。同事提议"按 Chinchilla 比例把模型放大 2 倍，数据照旧"。你同意吗？你会先做什么实验？</div><div class="dg-a"><ul><li><b>结论</b>：不同意。数据不变而参数翻倍，过拟合项同步增大，收益被抵消。</li><li><b>为什么</b>：Chinchilla 假设 D 随 C 增长；独立数据固定时，$N^\gamma/D^\delta$ 一项会随 N 上升（手算例子 1：N×2 只降 0.041，T×2 降 0.215）。</li><li><b>例子</b>：先用小模型扫"重复次数 × 权重衰减"，留候选短名单到大模型验证（2610.05126、2610.37842），再决定要不要加参数或加集成。</li><li><b>用到项目</b>：自己的小规模微调或继续预训练也适用：先扫 epoch 与 weight decay，再扩模型。</li></ul></div></div>

## 预训练数据、合成数据与 mid-training

### 价值与动机

**一句话**：RL 只能放大模型"已有的可能性"，mid-training 的任务是在 RL 之前把 agent 要用的行为分布铺出来。

<span class="fact">源文事实</span> 可学性论文（2609.38446，2026-09-29，**仅摘要**）把这个直觉理论化：奖励能指出正确答案，却不能决定新输入上该跑哪段计算；任务无关的"源观测"才能消除歧义。在 Qwen2.5 检查点上的实验里，用正确的源观测与首步监督训练的 Sequential 模型成功率 82.61%，对照（私有随机源）只有 44.15%；记忆回放保持检索的世界里任务成功率 75.32%，对比用"替代检索训练"的 49.86%。<span class="judge">解读者判断</span> 这是玩具世界 + 理论，用来建立方向感，不能直接换算成"某数据占比多少"。

### 做法：几个具体配方

<div class="dg-cards">
<div class="dg-card hot"><b>Qwen3-Coder-Next</b><i>2026-02-28 · 技术报告</i><p>80B 总参 / 3B 激活，从 Qwen3-Next 基座起做 mid-training</p><p>仓库级数据扩到约 600B token，训练上下文 32,768→262,144</p><p>原则：自然数据与合成数据平衡；含 PR、单轮 QA、多轮 agentic 编码</p><div class="dg-more">报告 §3.1 发现：同一 scaffold 内，mid-training token 越多越好；跨 scaffold 迁移有限（OpenHands 这类专用框架尤其明显）。</div></div>
<div class="dg-card hot"><b>Nemotron 开源 mid-training</b><i>2026-10-15 · 论文（仅摘要）</i><p>256K 上下文，数千亿 token，以自然 SWE 数据为主：打包仓库、PR、commit 历史、构建日志，外加少量 agent 轨迹</p><p>500B token 后，同样 SFT 下 SWE-bench Verified 60.7→64.5，Multilingual 55.8→62.8，Pro 32.0→35.5</p><div class="dg-more">更大的 Super 模型：280B token，DeepSWE 11.7→15.7，Verified 72.9→74.3。作者还指出过长的合成 SFT 可能损害后续 RL 可训练性。</div></div>
<div class="dg-card"><b>TrajLong</b><i>2026-10-04 · 论文（仅摘要）</i><p>把轨迹编译成长上下文任务：证据定位、跨证据聚合、时序状态维持</p><p>Qwen3-14B-Base 与 30B-A3B-Base，6 个长上下文 + 12 个 agent 基准</p></div>
<div class="dg-card"><b>Trajectory Soup</b><i>2026-09-29 · 论文（仅摘要）</i><p>mid-training 串行算力有上限；从共享检查点分叉多条分支再平均，在同算力下优于最强单条轨迹的平均</p></div>
</div>

<span class="judge">解读者判断</span> 三条共同线索：①**数据形态比数量更关键**——Nemotron 用的主要是自然工程数据，agent 轨迹只占小份；Qwen 强调要自然与合成平衡。②**长上下文与 agent 轨迹在 mid-training 里绑定**（256K、262K、TrajLong 都是长上下文）。③**mid-training 本身有算力天花板**（Trajectory Soup），多分支加平均比一条线拉长更有效。

**合成改写**（背景知识，本章未重读原文）：把网页文本用语言模型改写成多种风格，可以在高质量文本稀缺时扩出更多 token（如 Rephrasing the Web，arXiv 2401.16380；Nemotron-CC，arXiv 2412.02595）。它与上一节的开放问题直接相连：改写数据能否算公式里的独立数据 D，目前没有可靠定论，保守做法是把它当"打折的 D"，用小实验标定。

### 后续改进与对比

| 路线 | 数据 | 核心主张 | 证据级别 | 风险 |
|---|---|---|---|---|
| 工程自然数据 | 仓库、PR、commit、构建日志 | 先铺真实分布 | 开源配方，有消融（摘要数字） | 与具体 harness 绑定 |
| 合成轨迹 | 单轮 QA、多轮 agentic 编码 | 补充行为模式 | 技术报告 | 多样性、model collapse |
| 轨迹编译 | 长轨迹转长上下文任务 | 同时练长上下文与 agent 原子能力 | 预印本 | 规模较小 |
| 多分支 + 平均 | 同一数据多条分支 | 绕开串行算力上限 | 预印本 | 需要额外算力 |

**选型判断**：自己做 agent 基座，先把真实仓库类自然数据比例拉起来，再用少量轨迹校准格式；做小模型实验时优先试多分支平均，不要把一条 run 无限拉长。

### 难点与误区

- **开放问题**：合成轨迹的多样性与塌缩；mid-training 数据与 RL 环境的匹配（Qwen 报告显示跨 scaffold 迁移有限）；配比缺乏可迁移规律。
- **常见误区**：「mid-training 只是继续预训练」。它的作用是给 RL 铺能力先验，数据形态（轨迹、工具调用、长上下文）比 token 数量更重要。

<div class="dg-flash"><div class="dg-q">你想让一个开源 14B 基座在你的 agent 框架里更好用。预算有限，只能做一段 mid-training。你会先买"更多 token"，还是先定"数据形态"？依据是什么？</div><div class="dg-a"><ul><li><b>结论</b>：先定数据形态，且与你要用的 harness 对齐。</li><li><b>为什么</b>：Qwen3-Coder-Next 观察到同 scaffold 内 token 越多越好但跨 scaffold 迁移有限；Nemotron 配方的主体是自然工程数据加少量轨迹。</li><li><b>例子</b>：先用小比例（如 5%）的你框架里的真实轨迹，配大头的仓库 / PR 数据，跑短实验看 SFT 之后的目标基准。</li><li><b>用到项目</b>：把自己 Agent 的成功轨迹按 TrajLong 的"证据定位 / 聚合 / 状态维持"三类改写成训练样本，作为后续微调语料。</li></ul></div></div>

## 优化器：从 AdamW 到 Muon

### 价值与动机

**一句话**：Muon 把"每个权重矩阵的更新"从逐元素缩放改成"让所有方向的更新幅度一致"，希望同样的数据学得更快；但它的真实收益取决于你把基线调到多好。

<span class="fact">源文事实</span> 它已是旗舰配置：DeepSeek-V4（2026-04-26）"对大部分模块"使用 Muon，只有 embedding、预测头、mHC 的静态偏置与门控、所有 RMSNorm 权重仍用 AdamW，报告称带来更快收敛和更稳定的训练。Kimi K2（2025-07-28）的 MuonClip 在 15.5T token 上做到零 loss spike。Moonlight 仓库 README 称 Muon 在计算最优训练下约 2× 于 AdamW 的算力效率，（这一数字下面会被复核）。

### 原理：从"最陡下降"推出 $UV^\top$

**推导链**：

<div class="dg-flow steps">
<div class="dg-node"><b>SGD / Adam</b><span>沿梯度，逐元素缩放</span><div class="dg-more">缺陷：梯度矩阵常常"低秩、被少数大奇异值主导"，更新几乎只沿几个方向走。</div></div>
<div class="dg-node"><b>谱范数下最陡下降</b><span>限制 ‖ΔW‖ₒₚ ≤ η</span><div class="dg-more">换一个范数，最陡方向就变成 −η U Vᵀ（推导见正文）。</div></div>
<div class="dg-node hot"><b>正交化更新</b><span>所有奇异值抬到 1</span><div class="dg-more">相当于把梯度的奇异值全部抬到同一量级。</div></div>
<div class="dg-node"><b>Newton–Schulz</b><span>多项式近似，不做 SVD</span><div class="dg-more">奇异值上的奇多项式，只需矩阵乘，BF16 就能跑。</div></div>
<div class="dg-node"><b>RMS 对齐 + 权重衰减</b><span>沿用 AdamW 的学习率</span><div class="dg-more">DeepSeek-V4：把更新 RMS 缩到 0.18；动量 0.95，权重衰减 0.1。</div></div>
</div>

**记号**：梯度矩阵 $G\in\mathbb R^{m\times n}$ ，SVD 为 $G=U\Sigma V^\top$ ，奇异值 $\sigma_1\ge\sigma_2\ge\cdots$ ；$\lVert\cdot\rVert_\text{op}$ 是谱范数（最大奇异值）。

**第一步：谱范数约束下的最陡下降。** 想法：一次更新 ΔW 让一阶损失下降最多，即最小化 $\langle G,\Delta W\rangle=\mathrm{tr}(G^\top\Delta W)$ ，约束 $\lVert\Delta W\rVert_\text{op}\le\eta$ 。把 $G=U\Sigma V^\top$ 代入：

$$\langle G,\Delta W\rangle=\mathrm{tr}(\Sigma\,U^\top\Delta W\,V)=\sum_i \sigma_i\,[U^\top\Delta W V]_{ii}$$

$U^\top\Delta W V$ 的谱范数不超过 η，所以它的对角元绝对值都不超过 η，于是 $\langle G,\Delta W\rangle\ge-\eta\sum_i\sigma_i$ ，等号当 $U^\top\Delta WV=-\eta I$ 时取到，即

$$\Delta W=-\eta\,UV^\top$$

**直观含义**：SGD 的步长按 $\sigma_i$ 加权（大奇异值方向走得多），Muon 的步长对所有方向一视同仁，小奇异值方向被放大。

**第二步：不做 SVD，用 Newton–Schulz 近似 $UV^\top$ 。** 想法：对奇异值做奇多项式迭代，不用分解。令 $X=U\,\mathrm{diag}(s)\,V^\top$ ，则

$$p(X)=aX+b\,(XX^\top)X+c\,(XX^\top)^2X=U\,\mathrm{diag}\big(a s+b s^3+c s^5\big)\,V^\top$$

也就是说迭代在每个奇异值上**独立做一个标量映射** $s\mapsto as+bs^3+cs^5$ 。这个等式推一步：$XX^\top=U\,\mathrm{diag}(s^2)U^\top$ ，所以 $(XX^\top)X=U\,\mathrm{diag}(s^3)V^\top$ ，$(XX^\top)^2X$ 同理给 $s^5$ 。迭代开始前先除以 Frobenius 范数，保证 $s\in(0,1]$ 。

<span class="fact">源文事实</span> Keller Jordan 的实现用的系数是 $(a,b,c)=(3.4445,-4.7750,2.0315)$ ，其注释写明：选择"零点处斜率最大"的五次式，**不收敛到 1**，而是"约在 0.5–1.5 之间随机分布"，对性能没有影响。DeepSeek-V4 则做"混合 NS"共 10 步：前 8 步用同一组系数快速逼近，**最后 2 步换成 $(2,-1.5,0.5)$ 把奇异值精确钉在 1**。

**为什么最后两步这样换？** 检验第二组系数：$p(1)=2-1.5+0.5=1$ （1 是不动点），$p'(s)=2-4.5s^2+2.5s^4$ ，所以 $p'(1)=0$ 。导数为 0 说明 1 附近**二次收敛**；而第一组 $p(1)=3.4445-4.7750+2.0315=0.701$ ，1 不是不动点，系数换来的是前段"斜率大、快速拉起小奇异值"的能力。

**手算例子 3（让 NS 在 2×2 上跑起来）**。梯度 $G=\mathrm{diag}(3,1)$ ：SGD 更新的方向比例是 3:1。除以 $\lVert G\rVert_F=\sqrt{10}$ ，得到 $s=(0.9487,\,0.3162)$ 。用第一组系数对每个奇异值迭代一步：

- $s=0.9487$ ：$s^3=0.8538,\ s^5=0.7684$ ，$p=3.4445\times0.9487-4.7750\times0.8538+2.0315\times0.7684=3.2678-4.0768+1.5611=0.752$ 。
- $s=0.3162$ ：$s^3=0.0316,\ s^5=0.0032$ ，$p=1.0892-0.1510+0.0064=0.945$ 。

注意：一步之后原来的大值反而变成了 0.752，小值变成了 0.945，**两者交叉**。继续迭代（脚本核对的奇异值集合）：

| 步 | 奇异值集合 | 最大/最小 |
|---|---|---|
| 0 | {0.949, 0.316} | 3.00 |
| 1 | {0.945, 0.752} | 1.26 |
| 2 | {1.048, 0.757} | 1.38 |
| 3 | {1.041, 0.682} | 1.53 |
| 4 | {1.134, 0.683} | 1.66 |
| 5 | {1.134, 0.753} | 1.51 |

用 DeepSeek 的混合方案（8 步第一组 + 2 步第二组）：8 步后 {1.134, 0.682}，再 2 步变成 {1.0005, 1.0002}。**检查**：5 步的单组 NS 把 3:1 压到约 1.5:1，但没到 1:1；混合方案到 1.0003 以内，这就是它"把奇异值精确钉在 1"的含义。

<div class="dg-widget" data-src="widgets/muon_ns.html" data-height="330" data-title="拖动小奇异值比 r、步数，切换系数，看奇异值是否靠近 1"></div>

**第三步：RMS 对齐，复用 AdamW 的学习率。** 一个 $m\times n$（$m\le n$）、满秩的正交化矩阵 $UV^\top$ 的元素 RMS 是 $1/\sqrt n$ ，因为它有 m 个单位奇异值，Frobenius 范数平方为 m，元素总数 $mn$ ，故 $\mathrm{RMS}^2=m/(mn)=1/n$ 。

**手算例子 4**：1024×4096 的矩阵，正交化后 RMS 为 $1/\sqrt{4096}=0.015625$ （已用 numpy 对随机矩阵核对）。DeepSeek-V4 把更新 RMS 缩放到 0.18，因此乘上 $0.18\sqrt{4096}=11.52$ ，得到 $0.015625\times11.52=0.18$ 。**检查**：这样不同形状的矩阵更新幅度一致，并且量级接近 AdamW，所以可以沿用 AdamW 的学习率（V4 报告原话：reutilization of our AdamW hyper-parameters）。Moonlight 的做法类似，取系数约 0.2（**待核实**，以其论文 §2.2 为准）。

V4 的 Muon 配置：动量 0.95、权重衰减 0.1、RMS 缩放到 0.18；峰值学习率 2.7×10⁻⁴，最后按余弦降到 2.7×10⁻⁵；batch 从小增到 75.5M token。

**MuonClip / QK-Clip**（K2 报告，细节待核实）：Muon 让注意力 logit 容易爆炸；K2 的办法是监控每头最大 logit，超过阈值就按比例缩小该头的 $W_q,W_k$ 。DeepSeek-V4 **没有采用**这一招，因为它的注意力架构对 query 与 KV 直接做 RMSNorm，从结构上防住了 logit 爆炸（V4 §2.4）。

### 在代码里看

- **仓库**：[KellerJordan/Muon](https://github.com/KellerJordan/Muon)（约 2.9k star，最近提交 2026-05），文件 [muon.py](https://github.com/KellerJordan/Muon/blob/master/muon.py)；对照 [MoonshotAI/Moonlight](https://github.com/MoonshotAI/Moonlight) 的 `examples/toy_train.py`（我只核实了该文件存在，没有逐行读）。
- **关键代码**（节选自 `zeropower_via_newtonschulz5`，已核对）：

```python
a, b, c = (3.4445, -4.7750,  2.0315)
X = X / (X.norm(dim=(-2, -1), keepdim=True) + 1e-7)
for _ in range(steps):
    A = X @ X.mT
    B = b * A + c * A @ A
    X = a * X + B @ X
```

  对照公式：第二行是"除以 Frobenius 范数"；`A = XXᵀ` 是 $XX^\top$ ；`B = bA + cA²`，所以 `B @ X` 就是 $b\,XX^\top X+c\,(XX^\top)^2X$ ，再加 `a * X` 得到 $p(X)$ 。`muon_update` 末尾 `update *= max(1, m/n)**0.5` 是对高瘦矩阵的 RMS 补偿。
- **工程细节**：①代码里把 $G$ 转成 `bfloat16`；高瘦矩阵先转置，使 `X @ X.mT` 的尺寸更小；②只用于隐藏层 2D 权重，embedding、输出层、增益与偏置用 AdamW；③V4 的分布式实现里 Muon 要完整梯度矩阵，与 ZeRO 逐元素分片冲突，于是设计了"混合 ZeRO 分桶"，MoE 里每个专家独立优化（V4 §3.4.1）。

### 复核：Muon 的优势有多少是真的

<span class="fact">源文事实</span> 「Tune the Baseline First」（2611.02529，2026-11-02，预印本）在 MAI-Base-2 协议下，把 LR 与 WD 的乘积（LR·WD）对每种方法联合调好，用 1.9M–15M 活跃参数的 MoE 缩放梯子（固定每活跃参数的 token 数与重复次数）：

- **共享同一组 LR·WD 时**：Muon-SW（带缩放权重衰减的 Muon）领先 0.035 BPB，折合 **1.52×** 算力节省。
- **各自调好后**：差距只剩 0.0026 BPB（95% CI [0.0018, 0.0034]），折合 **1.03×**。约 90% 的"优势"来自基线没调好。
- 剩下的是真的：最小尺寸的 4 个配对种子都偏向 Muon-SW；而且这份优势**随规模变大**：8× 活跃参数范围内，调好之后的差距 0.0036→0.0051 BPB，"存活占比"约 10%→21%。
- 最优的 LR·WD 随规模增长，且 Muon-SW 增得更快（比值 1.40→1.91）；用两个最小规模拟合的律，外推到第三个规模会高估 1.3–1.5×。

![图4：联合调 LR·WD 后，基线几乎追平 Muon-SW（原文 Fig.1，节选）](figs/fig4.png)

> 图4 说明（原图，从 PDF 第 5 页裁出）：三列是三个规模（L3=1.9M、L4=3.9M、L6=15.0M 活跃参数），横轴是 LR·WD 倍率 p（对数），纵轴是留出集 BPB（越低越好）。蓝线是常数权重衰减，橙线是 Muon-SW。虚线是共享设置 p=1：此处橙线明显更低。但点线（各自的最优点）显示蓝线的最优点在 p 小得多的地方，在那里两条线几乎重叠。它支撑的论点：**同设置比较会高估 Muon；先调基线，差距大部分消失，只留下一个随规模增长的小优势**。

<details><summary>原文摘录 · arXiv 2611.02529 摘要</summary>

> Most of the gain is a tuning gap. At the shared setting Muon-SW wins by 0.035 bits per byte (BPB), a 1.52x compute saving; after both methods are tuned, the gap is 0.0026 BPB (95% CI [0.0018, 0.0034]), a 1.03x saving, so about 90% of the advantage disappears.

</details>

<span class="judge">解读者判断</span> 注意这篇研究的边界：最大只有 15M 活跃参数，作者自己也说 L4、L6 来自单一种子、且最优点在扫描区边缘附近；它没有说 Muon 在 1T 参数下没有优势，只说**别用没调好的基线下结论**。

<span class="fact">源文事实</span> 另一篇（2611.03633，2026-11-02）从不同角度补刀：**预训练数据规模会反转 Muon 与 AdamW 的微调差距**——预训练数据超过一定量后，AdamW 在微调后反超 Muon；模型越大，反超发生的 token/参数比越低。作者用"间隔与离散度之比"（margin-to-spread）解释：数据少时 Muon 更大，数据多时 AdamW 更大，并在线性联想记忆里证明了这一趋势。<span class="judge">解读者判断</span> 这指的是**微调后**的表现而不是预训练 loss，所以并不与 DeepSeek-V4 用 Muon 矛盾，但它提醒我们：过训练到每参数上千 token（前文 Flash 约 2462）恰恰是这篇预测 AdamW 可能更有优势的区间，目前没有一手证据说明 V4 在这个区间的取舍。

### 后续改进与对比

<div class="dg-timeline">
<div class="dg-event"><i>2024</i><b>Muon</b><span>隐藏层用 NS 正交化更新，NanoGPT 速通</span></div>
<div class="dg-event"><i>2025-02</i><b>Moonlight</b><span>加权重衰减、对齐更新 RMS，扩展到 3B/16B MoE</span></div>
<div class="dg-event"><i>2025-07</i><b>Kimi K2 MuonClip</b><span>QK-Clip 压住注意力 logit，1T 参数零 loss spike</span></div>
<div class="dg-event hot"><i>2026-04</i><b>DeepSeek-V4</b><span>混合 NS 8+2，RMSNorm 代替 QK-Clip</span></div>
<div class="dg-event"><i>2026-11</i><b>两篇复核</b><span>调好基线后优势缩到约 1.03×；数据规模反转微调差距</span></div>
</div>

| 优化器 | 核心 | 额外状态 | 代价 | 证据与边界 |
|---|---|---|---|---|
| AdamW | 逐元素二阶矩缩放 | 两份 | 低 | 基线；调好后差距很小 |
| Muon | 正交化动量 | 一份 | NS 的矩阵乘；分布式要完整梯度 | 旗舰采用；真实优势小但随规模增大（1.9M–15M） |
| Muon + QK-Clip | 再限制注意力 logit | 一份 | 额外监控 | K2 零 loss spike |
| Muon + RMSNorm（V4） | 结构上防 logit 爆炸 | 一份 | 需要架构配合 | V4 §2.4 |

**选型判断**：自己训小模型，先把 AdamW 的 LR·WD 扫到极优再比；想用 Muon，就把它的 LR·WD 也扫一遍，并确认是否需要对注意力 logit 做约束。

**常见误区**：「Muon 全面优于 AdamW」：最新证据显示差距很大程度取决于调参与数据规模。

<div class="dg-flash"><div class="dg-q">同事说"Muon 比 AdamW 省了 1.5× 算力，建议全组切换"。你会先问哪个问题？如果答案是"没单独调 AdamW"，你预期结果会怎样？</div><div class="dg-a"><ul><li><b>结论</b>：先问两边的 LR·WD 是否各自联合调好。</li><li><b>为什么</b>：共享同一组超参时，基线的最优点离得很远，比较等于在基线的非最优点上量；两种方法的最优 LR·WD 还会随规模改变。</li><li><b>例子</b>：Tune the Baseline First：未调时领先 0.035 BPB（1.52×），调好后 0.0026 BPB（1.03×），约 90% 消失。</li><li><b>用到项目</b>：自己跑优化器对比时，每种方法至少扫 3–5 个 LR·WD 倍率，在曲线最低点比较，并跨两个规模看趋势。</li></ul></div></div>

## 低精度：FP8、FP4 与训推一致

### 价值与动机

**一句话**：精度每降一档，矩阵乘的吞吐与显存大约翻一番；但 4 bit 只有 8 个幅值，必须靠"分块缩放"才能表示一个张量，代价是更多数值麻烦。

<span class="fact">源文事实</span> 现实用量：DeepSeek-V4 的路由专家参数使用 FP4 精度（FP4×FP8 峰值算力在现有硬件上与 FP8×FP8 相同，理论上未来硬件可高 1/3），并在后训练阶段对 MoE 专家权重与 indexer 的 QK 路径做 FP4 量化感知训练（V4 §5.2.1）。Jet-RL（2601.14243，2026-01-20）指出 RL 里 rollout 占总训练时间超过 70%，因此对 rollout 做 FP8 最诱人。

### 原理：块缩放与"转置不一致"

**FP4（E2M1）的可表示幅值**：{0, 0.5, 1, 1.5, 2, 3, 4, 6}，只有 8 个。因此一个张量要分成小块，每块配一个缩放 $s=\max|x|/6$ ，把块内值除以 s 再取最近的格点（NVFP4 常见做法是每 16 个元素一个 FP8 缩放，MXFP4 是每 32 个元素一个 E8M0 缩放；这是规格背景知识，非本章论文）。

**关键陷阱**：线性层前向用 $W$ ，反向用 $W^\top$ 。1D 块沿"最后一维"切，所以转置后**同一个元素落进了另一个块**，拿到另一个缩放。<span class="fact">源文事实</span> Stable FP4 Training（2607.24953，2026-07-27）把 FP4 不稳定的根源定位于此：**转置带来的缩放不一致，使前向和反向对同一个权重用了不同的量化值，造成有偏、不稳定的梯度更新**。

**手算例子 5**（脚本核对）。取 4×4 的 W，第一行 [0.4, 0.5, 0.6, 5.0]，第二行 [0.3, 0.2, 0.9, 0.7]，1D 块 = 沿行连续 2 个元素：

- 前向（行内块）：元素 W[0,2]=0.6 与 5.0 同块，$s=5/6=0.8333$ ，$0.6/0.8333=0.72$ ，最近格点 0.5，反量化得 $0.5\times0.8333=0.4167$ （误差 31%）。
- 反向（对 $W^\top$ 切块，即沿 W 的列切）：W[0,2]=0.6 与 W[1,2]=0.9 同块，$s=0.9/6=0.15$ ，$0.6/0.15=4$ 恰好是格点，得 0.6，**无误差**。
- 同一个 W[0,2]：前向 0.4167，反向 0.6，差 0.183。再看 W[1,3]=0.7：前向 0.6，反向 0.8333，差 0.233（33%）。

**检查**：一个离群值 5.0 只在前向里"拖垮"了它的邻居，在反向里不拖。改用 2×2 方块缩放后，转置前后取到的块完全一致（脚本验证 $Q(W^\top)=Q(W)^\top$ ），不一致消失；代价是总绝对误差略大（本例 1D 前向总误差 0.517，2D 为 0.683），这是"一致"与"精度"的交换。

<div class="dg-widget" data-src="widgets/fp4_block.html" data-height="420" data-title="拖动离群值，切换 1D / 2D 分块，看红色（前向反向不一致）的格子"></div>

![图5：1D 块与 2D 块在转置前后的缩放（Stable FP4 Fig.1，原文）](figs/fig5.png)

> 图5 说明（原图，arXiv 2607.24953 html）：(a) 1D 块：W 转置后块的方向变了，同一元素换到别的块，缩放 $s\to s'$ 变化，右边 t-SNE 里前向（蓝）和反向（红）的分布不重合；(b) 2D 块：块是方形，转置后块内元素不变，前向与反向分布重合；(c) 下排热图：1D 的缩放差 $|S_\text{fwd}-S_\text{bwd}|$ 最高到 2.0，有效权重偏差高达 0.2；2D 几乎为 0。它支撑的论点：**FP4 不稳定的一个具体根源是转置不一致，用 2D 块量化就能消掉**。

**第二个工程件：随机舍入。** 最近邻取整是有偏的：x=0.7 在格点 0.5 与 1.0 之间，最近邻总得到 0.5（偏差 −0.2）。随机舍入让落到 1.0 的概率为 $(0.7-0.5)/(1.0-0.5)=0.4$ ，期望 $0.5+0.5\times0.4=0.7$ ，**无偏**。梯度要累加几万步，偏差会累积，所以 FP4 梯度用随机舍入。Stable FP4 把 2D 块、无截断缩放、随机舍入三者组合，另对 Q、K 投影用 MXFP8（注意力对精度敏感），在最多 7B 稠密与 30B MoE、100B token 上稳定训练，困惑度与下游精度相对 BF16 退化不到 1.3%。

### FP8/FP4 的 RL：训推一致

<span class="fact">源文事实</span> **Jet-RL**（2601.14243）：常见做法"训练用 BF16、rollout 用 FP8"在长 horizon 与难任务上会严重失稳甚至精度塌缩，原因是这实际上变成了 off-policy，训练与推理的数值失配很大；Jet-RL 让训练和 rollout 用**统一的 FP8 精度流**，不需要跨步校准，rollout 阶段最多提速 33%。

**MoE 的 FP4 RL 有个新坑：路由器**（2611.04376，2026-11-03，预印本）。作者发现稠密模型上有效的"恢复"配方，在 MoE 上与朴素 FP4 基线相比**毫无改进**；根因是路由器做的是离散的专家选择，训推对齐对"恢复技术是否在两侧对称使用"极其敏感。

![图6：朴素 FP4（HiF4）下，训练概率与推理概率散点（原文 Fig.1 之一）](figs/fig6.png)

![图7：训练与推理两侧都做恢复（RC Both）后的散点（原文 Fig.1 之一）](figs/fig7.png)

> 图6、图7 说明（原图，arXiv 2611.04376 html）：每个点是同一个 token 在训练侧与推理侧算出的概率，对角线 y=x 代表完全一致，n=5120。图6 朴素 FP4 的 Pearson 相关 PCC=0.9410，点云明显散开；图7 两侧都做恢复后 PCC=0.9940，点紧贴对角线。论文表 2 另给：BF16 的 PCC 为 0.9951；只在推理侧恢复 0.9444，只在训练侧 0.9580，两侧 0.9940。第 12 层 top-k 路由匹配率：BF16 0.8799，朴素 FP4 0.6172，两侧恢复 0.8682。它们支撑的论点：**单侧恢复几乎无效，对称恢复才把对齐拉回 BF16 水平**（MoEResQ 的核心原则）。

<span class="judge">解读者判断</span> 路由匹配率说明了为什么 MoE 特别难：top-k 是离散选择，logit 一点点量化噪声就会改变选中的专家，于是同一个 token 在训练和 rollout 里走了不同的专家。顺带注意：**即使 BF16，训推路由匹配率也只有 0.88**（第 12 层），所以"完全一致"本身就不存在，要比较的是与 BF16 的差距。

### 在代码里看

- **仓库**：[NVIDIA/TransformerEngine](https://github.com/NVIDIA/TransformerEngine)（约 3.6k star，最近提交 2026-10-31），配方类在 [transformer_engine/common/recipe/__init__.py](https://github.com/NVIDIA/TransformerEngine/blob/main/transformer_engine/common/recipe/__init__.py) 的 `NVFP4BlockScaling`；底层 kernel 在 `transformer_engine/common/recipe/nvfp4.cu`（同目录还有 `fp8_block_scaling.cu`、`mxfp8_scaling.cu`）。
- **对应关系**：该配方暴露了三个开关：`random_hadamard_transform`、`stochastic_rounding`、`fp4_2d_quantization`（我读到了字段定义，没有逐行跟进实现）。对照本章：`stochastic_rounding` 对应上面的无偏舍入；`fp4_2d_quantization` 对应 2D 块（转置一致）；Hadamard 变换是把离群值"摊平"以缩小块内动态范围的另一类做法。
- **在 RL 里**：端到端 FP4 RL 的 MoE 恢复（MoEResQ）我没有找到可靠的开源实现，**暂无可靠开源实现**。

### 后续改进与对比

| 精度 | 做法 | 主要风险 | 证据 |
|---|---|---|---|
| BF16 | 基线 | 慢、占显存 | — |
| FP8 + block scaling | 训练 / rollout 同精度流（Jet-RL） | 训推不一致 | rollout 最多 +33% |
| FP4 预训练 | 2D 块 + 随机舍入 + 注意力 Q/K 保 MXFP8 | 转置不一致、梯度偏差 | ≤7B 稠密 / 30B MoE，100B token，退化 <1.3% |
| FP4 后训练量化感知 | 专家权重 + indexer QK（V4） | 精度回落 | V4 报告 |
| FP4 RL（MoE） | 训练 / 推理两侧对称恢复 | 路由器失配 | 预印本，PCC 0.941→0.994 |

**选型判断**：先上 FP8 并保证训练与 rollout 精度流一致；FP4 只有在你能监控训推概率的相关性（PCC）和路由匹配率时才值得上；MoE 的 FP4 RL 记住"两侧都做"。

**难点与误区**：开放问题包括低精度本身的 scaling 规律（至今无统一公式）、FP4 RL 在更大规模是否仍成立（现有证据 ≤30B）。常见误区：「FP4 不稳定是因为位数太少」：Stable FP4 的结论是一个具体的、可修的原因——转置不一致，加上梯度的有偏舍入。

<div class="dg-flash"><div class="dg-q">你在一个 30B MoE 上做 FP4 的 RL，只在 rollout 侧套了稠密模型的恢复配方，训练曲线没改善。你会怎么排查？</div><div class="dg-a"><ul><li><b>结论</b>：先量训练概率与推理概率的 PCC 以及路由 top-k 匹配率，再把恢复配方改成两侧对称。</li><li><b>为什么</b>：路由器是离散选择，单侧恢复让训练与推理在选专家时分歧；2611.04376 显示单侧恢复几乎无改善。</li><li><b>例子</b>：该文表 2：只推理侧 PCC 0.9444，只训练侧 0.9580，两侧 0.9940，BF16 为 0.9951。</li><li><b>用到项目</b>：任何训推分离的 RL 流程，把"训练概率 vs 推理概率"的散点或相关系数做成常驻监控。</li></ul></div></div>

## 一条主线走一遍

**场景**：你要给团队的 agent 产品做一个 30B 级 MoE 基座，独立高质量数据只有约 1T token，要一路走到 agent RL。

1. **算力怎么分**：算一下 tokens/参数。30B 总参、3B 激活、1T 数据，约 333 token/激活参数，已是约 17 倍 Chinchilla 过训练，再放大数据只能重复。先用小模型扫"重复次数 × 权重衰减"，留候选短名单到大模型验证（2610.05126、2610.37842）；用 Practical Scaling Laws 的三项形式判断：若欠训练项占大头就多训，若过拟合项占大头就不要再加参数。
2. **优化器**：先把 AdamW 的 LR·WD 扫到最优，再试 Muon（动量 0.95、WD 0.1、更新 RMS 0.18 作起点，V4 配置），两边都扫，在曲线最低点比；若出现注意力 logit 爆炸，按 V4 的做法先在结构上加 RMSNorm，其次才考虑 QK-Clip。
3. **精度**：预训练用 FP8；FP4 只在 2D 块 + 随机舍入 + Q/K 保 MXFP8 的组合下尝试（Stable FP4），监控 loss 与 BF16 的差。
4. **mid-training**：长上下文到 256K，混入仓库、PR、commit、构建日志类自然数据，再加少量 agent 轨迹；拿多条分支做平均（Trajectory Soup 的思路），在你要用的 harness 上做短评测（Qwen 报告显示跨 scaffold 迁移有限）。
5. **RL**：先跑小规模，用 ScaleRL 的 sigmoid 拟合 A 与 $C_\text{mid}$ ，判断瓶颈是上限还是效率。如果用 FP8/FP4 rollout，保持训推同精度流（Jet-RL），MoE 用对称恢复并监控 PCC 与路由匹配。

## 我的判断框架

1. **先问数据**：独立数据够吗？够就过训练（看推理量），不够就先调重复次数与权重衰减，别急着加参数。
2. **先问基线**：任何"X 比 Y 省 N 倍算力"，先问 Y 是否调到极优、是否在同一规模、是否跨了两个规模。
3. **先问上限还是效率**：RL 的改进是抬高 A，还是左移 $C_\text{mid}$ ？只改效率的技巧换一个预算就不重要了。
4. **先问数据形态**：mid-training 看数据形态与目标 harness 的对齐，而不是 token 数。
5. **先问对称性**：低精度里训练与推理、前向与反向、两侧恢复，凡是"不对称"的地方就是 bug 的位置。
6. **先问证据级别**：本章最新结论大多是预印本、≤15M 活跃参数的小梯子；上到旗舰规模是外推，要降一档置信度。

## 与已学内容的联系

- **前置章节**：第 2 章「预训练·结构：长、宽、深怎么设计」给出 N（含 MoE 的稀疏度）；本章的 scaling 公式把 N 当变量。第 1 章「基座三问」的总图把预训练、mid-training、RL 放在同一条线上，本章是其中"信号与算力"的细化。第 3 章 KDA 与本章共享"数值范围"的思考（衰减下界、低精度）。
- **平台上已有计划**：CS336 课程计划（计划 5）里有 Muon、scaling law、混合精度等课时，本章可作为它们的 2026 年更新；「基座模型前沿跟进」（计划 9）是本计划的上位清单。
- **已深读条目**：
  - [CompressionBench：你的编码 Agent 如何压缩 LLM](#learn/item/41)：让 Agent 在存储上限与隐藏准确率门槛下压缩模型，与本章的低精度选择（FP8 / FP4 量化）直接相关，见测试第 5 题。
  - [Adversarial Speculative Reasoning](#learn/item/39)：投机解码验证块里越靠后的位置数值噪声越大（约每格 +4%），与本章"数值失配会改变离散决策"同源，属于推理侧的另一例。
  - [There is no posttraining data commons](#learn/item/29)：后训练数据没有公共集，对应本章"合成数据算不算新数据、配比缺乏可迁移规律"这一开放问题。
  - [cheapest way to learn reinforcement learning](#learn/item/15)：低成本学 RL 的路径，可配合本章 RL 曲线拟合做小实验。
- **产业落地（来自模型报告，创业公司库里没有直接对应条目）**：Muon 与 FP4 已在 DeepSeek-V4（32T / 33T token，Muon、专家 FP4）、Kimi K2（MuonClip，15.5T token）上用于旗舰；Qwen3-Coder-Next 与 Nvidia Nemotron 已把 mid-training 作为 agent 能力的关键阶段。没有被采用的场景：V4 不用 QK-Clip，是因为结构上已经有 RMSNorm。

## 动手：90 分钟最小实验

1. **验证"基线调好后差距缩水"**：克隆 [modded-nanogpt](https://github.com/KellerJordan/modded-nanogpt)（约 6k star，最近提交 2026-09），在小模型上跑 AdamW 与 Muon 各 5 个 LR·WD 倍率。预期：同一组共享超参下 Muon 领先，各自取最优后差距明显缩小。
2. **验证 NS 的奇异值行为**：在 numpy 里写 20 行：随机 64×256 矩阵，按 `muon.py` 的系数迭代 5 步，并对比"前 8 步 + 后 2 步 $(2,-1.5,0.5)$"，打印奇异值的最小/最大值。预期：单组 5 步落在约 0.7–1.2；混合 10 步全部在 1±0.01。
3. **验证随机舍入无偏**：对 0.7 在格点 {0.5, 1.0} 上各做 10 万次最近邻与随机舍入，求均值。预期：最近邻恒为 0.5，随机舍入均值约 0.70。

## 延伸阅读

- [Practical Scaling Laws](https://arxiv.org/abs/2605.09189)：读第 2 节的公式推导与 Table 4 的成本感知分配，理解饱和形式。
- [The Art of Scaling RL Compute (ScaleRL)](https://arxiv.org/abs/2510.13786)：读 Fig.1、Fig.4 与"配方消融"，学会用 sigmoid 判断改进是上限还是效率。
- [Tune the Baseline First](https://arxiv.org/abs/2611.02529)：读 Table 1 与 §5，看评估优化器的"正确姿势"。
- [DeepSeek-V4 Technical Report](https://arxiv.org/abs/2606.19348)：读 §2.4 Muon 配置与 §3.4.1 分布式实现，以及 §5.2.1 的 FP4 QAT。
- [Stable FP4 Training](https://arxiv.org/abs/2607.24953)：读 Fig.1 与 Fig.2，理解转置不一致的来龙去脉。
- [Aligning Training and Rollout Policies for End-to-End FP4 RL on MoE LLMs](https://arxiv.org/abs/2611.04376)：读 Table 2，理解对称恢复。
