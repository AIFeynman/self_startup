> **本节目标**：从标准注意力出发，一步步推出 Kimi K3 用的 KDA 递推式 $S_t=(I-\beta_t k_t k_t^\top)\,\mathrm{Diag}(\alpha_t)\,S_{t-1}+\beta_t k_t v_t^\top$ ，知道每一项从哪来、去掉它会坏在哪，并能拿 2 维小例子在纸上算一遍。
> **学完能回答**：① 线性注意力的「状态矩阵」是怎么从 softmax 注意力变出来的？② delta rule 为什么就是一步在线梯度下降？③ 为什么 $k$ 必须归一化， $\beta$ 必须在 (0,1) 之间？④ K3 为什么给衰减加 −5 的下界，又为什么还要留 1/4 的全注意力层？⑤ KDA 和 Mamba2、GLA、Gated DeltaNet、RWKV-7 各差在哪，什么时候选哪个？
> **预计用时**：120–150 分钟。建议准备纸笔，每个算例先自己算再往下看。
> **前置**：矩阵乘法、外积、对一个平方误差求导。不需要事先懂 RNN 或 SSM。

## 资料时效

- **Kimi K3 Technical Report**（2026-07-27）§2.1.1：KDA 在 K3 里的最新形式，包括有下界的衰减和全秩输出门。数值与工程细节以它为准，是主读物。
- **Kimi Linear**（arXiv 2510.26692，2025-10-30）：KDA 的原始论文，§2.2 的推导链和 §3.1 的分块算法最完整。发表略超一年，但 K3 原文明确写「UT 变换和分块推导见 Kimi Linear」，所以推导部分仍读它。
- 本节所有公式都对照两篇原文核过；所有算例的数字都用脚本复算过。

## 为什么要学它：价值与动机

**一句话**：KDA 要解决的是「上下文越长，推理越贵、越占显存」这个问题。长上下文 Agent（读整个仓库、几百轮工具调用）把这个问题从论文里的担忧变成了每天的账单。

<span class="judge">解读者判断</span> 先用一个可复算的估算看问题有多大。**假设**一个全注意力层有 8 个 KV 头、每头 128 维、K 和 V 各存一份、BF16 每个数 2 字节：

- 每个 token 每层的 KV cache： $8\times128\times2\times2=4096$ 字节，约 4 KB。
- 1M token、1 层：约 4.1 GB；60 层：约 246 GB。一张 80 GB 的卡连一条请求的 cache 都放不下。
- 每生成一个 token，都要把这几百 GB 从显存读一遍。解码因此受显存带宽限制，长度翻倍，每步耗时也接近翻倍。

换成线性注意力（KDA 属于这一类），每个头只存一个 $d_k\times d_v=128\times128$ 的状态矩阵，BF16 下 32 KB，**和长度无关**。这就是第 7 节那组数字的来源：1M 上下文下解码快 6.3 倍，KV cache 最多省 75%（剩下的 25% 来自保留的 MLA 层）。

为什么现在必须学：

1. **前沿模型在换结构**。<span class="fact">源文事实</span> Kimi K3 的 93 层里有 69 层是 KDA；Qwen3-Next 用 Gated DeltaNet 与注意力 3:1 混合。读懂这些技术报告的结构表，前提就是懂这条推导链。
2. **它是一条主线，不是一个孤立技巧**。从线性注意力、DeltaNet、GDN 到 KDA，再到第 8 节的 RWKV-7、DeltaProduct、Titans，都在回答同一个问题：固定大小的记忆该怎么写、怎么忘。学会这一条，后面的新论文多半能定位成「在哪一步改了什么」。
3. **它决定产品能力的边界**。状态有损，所以混合比例、召回能力、前缀缓存都受它影响（第 7 节）。选基座、设计长上下文评测时都要用到。

## 全景图：一条推导链，每一步补上一步的缺陷

KDA 不是凭空设计的。它是从标准注意力出发，连续修了五个缺陷得到的。点「下一步」逐个看每一步修了什么、还剩什么问题。

<div class="dg-flow steps">
<div class="dg-node"><b>Softmax 注意力</b><span>每步回看全部历史</span><div class="dg-more">每生成一个 token，都要和之前所有 key 做点积，还要存下全部 K、V。长度翻倍，KV cache 翻倍，训练计算量翻四倍。</div></div>
<div class="dg-node"><b>线性注意力</b><span>历史压成一个矩阵 S</span><div class="dg-more">去掉 softmax 以后，可以先把 k、v 合并进固定大小的状态 S，内存不再随长度增长。缺陷：只加不减，写错了改不掉，相近的 key 会串味。</div></div>
<div class="dg-node"><b>DeltaNet</b><span>先读再写，只写误差</span><div class="dg-more">写入前先读出记忆里的旧值，只写入「新值 − 旧值」。这样能改写，也就是对重构误差做一步梯度下降。缺陷：和新 key 无关的旧内容永远不会淡出。</div></div>
<div class="dg-node"><b>Gated DeltaNet</b><span>整体乘 α，开始遗忘</span><div class="dg-more">每一步先把整个状态乘一个标量 α∈(0,1)，相当于给记忆做 weight decay。缺陷：所有通道只能用同一个遗忘速度。</div></div>
<div class="dg-node hot"><b>KDA</b><span>每个通道一个 α</span><div class="dg-more">把标量 α 换成对角矩阵 Diag(α)，每个 key 通道有自己的遗忘速度。K3 又给 α 加了下界 e^−5，训练内核因此全部能走 Tensor Core。</div></div>
<div class="dg-node"><b>3:1 混合</b><span>留 MLA 做精确召回</span><div class="dg-more">固定大小的状态终究是有损压缩。K3 每 3 层 KDA 配 1 层全注意力（Gated MLA），由 MLA 层负责「从一百万个 token 里精确找回某一句」。</div></div>
</div>

| 模型 | 状态更新 | 修了什么 | 还剩什么问题 |
|-|-|-|-|
| 线性注意力 | $S_t=S_{t-1}+k_t v_t^\top$ | 内存固定，不随长度增长 | 改不掉，会串味 |
| DeltaNet | $S_t=(I-\beta_t k_t k_t^\top)S_{t-1}+\beta_t k_t v_t^\top$ | 能改写 | 不会遗忘 |
| Gated DeltaNet | $S_t=\alpha_t(I-\beta_t k_t k_t^\top)S_{t-1}+\beta_t k_t v_t^\top$ | 会遗忘 | 所有通道同一速度 |
| KDA | $S_t=(I-\beta_t k_t k_t^\top)\mathrm{Diag}(\alpha_t)S_{t-1}+\beta_t k_t v_t^\top$ | 每个通道各自遗忘 | 状态容量有限，仍需全注意力层 |

## 0 先把记号和形状对齐

下面都只看**一个注意力头**。每个 token 有三个列向量：查询 $q_t\in\mathbb{R}^{d_k}$ ，键 $k_t\in\mathbb{R}^{d_k}$ ，值 $v_t\in\mathbb{R}^{d_v}$ 。Kimi Linear 里 $d_k=d_v=128$ 。

**外积** $k v^\top$ 是一个 $d_k\times d_v$ 的矩阵，第 $i$ 行等于 $k_i\cdot v^\top$ 。例如 $k=(1,0)$ ， $v=(1,2)$ ：

$$
k v^\top=\begin{bmatrix}1\\0\end{bmatrix}\begin{bmatrix}1&2\end{bmatrix}=\begin{bmatrix}1&2\\0&0\end{bmatrix}
$$

**读出**写成 $S^\top q$ ，结果是 $d_v$ 维向量。它等于 $\sum_i q_i\cdot(S\text{ 的第 }i\text{ 行})$ ，即用 $q$ 的各分量去加权 $S$ 的各行。

请记住这个「行视角」：**状态 $S$ 的第 $i$ 行，就是 key 的第 $i$ 个通道上存的内容**。第 5 节的逐通道遗忘就是逐行乘一个数。

## 1 起点：softmax 注意力贵在哪

标准注意力在第 $t$ 步的输出是：

$$
o_t=\sum_{i\le t}\frac{\exp(q_t^\top k_i/\sqrt{d_k})}{\sum_{j\le t}\exp(q_t^\top k_j/\sqrt{d_k})}\,v_i
$$

生成第 $t$ 个 token 时，新的 $q_t$ 要和前面全部 $t$ 个 key 都做一次点积，所以 K、V 必须全部存着。长度为 $T$ 时：

- **训练**：每层大约 $2T^2d_h$ 次浮点运算，是平方增长。
- **解码**：第 $t$ 步计算量是 $O(t)$ ；KV cache 随长度线性增长。

能不能先把历史「合并好」存起来？对 softmax 不行。分母要用到当前 $q_t$ 和**所有** key 的点积，而 $\exp(q^\top k)$ 不能写成「只含 $q$ 的部分」乘「只含 $k$ 的部分」（有限维内做不到）。所以每来一个新 $q$ ，都得把所有 key 重新算一遍。**根子在 softmax**。

<div class="dg-flash"><div class="dg-q">上下文从 128k 扩到 1M（约 8 倍），softmax 注意力层在训练和解码上各会贵多少？为什么不能像 RNN 那样只存一个固定大小的「摘要」？</div><div class="dg-a"><ul><li><b>结论</b>：训练的注意力计算约贵 64 倍（平方），解码每步约贵 8 倍，KV cache 也大 8 倍。</li><li><b>为什么</b>：softmax 的归一化把当前 q 和全部 key 绑在一起，exp(q·k) 不能拆成 q 的函数乘 k 的函数，所以无法预先合并历史。</li><li><b>例子</b>：按 Kimi Linear §6.3 的公式，全注意力每层每头是 2T²d_h；T=1M、d_h=128 时约 2.6×10^14 次运算。</li></ul></div></div>

## 2 去掉 softmax：历史变成一个矩阵

最直接的办法是把 softmax 去掉，只保留点积（实际模型会先对 $q$ 、 $k$ 做特征映射和归一化，这里先忽略）：

$$
o_t=\sum_{i\le t}(q_t^\top k_i)\,v_i
$$

**关键一步是换乘法顺序。** $q_t^\top k_i$ 是标量，所以 $(q_t^\top k_i)\,v_i=v_i\,(k_i^\top q_t)$ ，于是

$$
o_t=\sum_{i\le t}v_i\,k_i^\top q_t=\Big(\sum_{i\le t}v_i k_i^\top\Big)q_t
$$

括号里的东西与 $q_t$ 无关，可以提前累加。按论文的写法，把它转置后记为状态

$$
S_t=\sum_{i\le t}k_i v_i^\top\in\mathbb{R}^{d_k\times d_v},\qquad o_t=S_t^\top q_t,\qquad S_t=S_{t-1}+k_t v_t^\top
$$

原来每步要做 $t$ 次点积；现在每步只更新一个 $d_k\times d_v$ 的矩阵。**内存与长度无关**：一个头永远是 $128\times128=16384$ 个数。

**手算 1：写入两条，再读出。** 取 $d_k=d_v=2$ ：

- 第 1 条： $k_1=(1,0)$ ， $v_1=(1,2)$ 。
- 第 2 条： $k_2=(0,1)$ ， $v_2=(3,-1)$ 。

$$
S=k_1v_1^\top+k_2v_2^\top=\begin{bmatrix}1&2\\0&0\end{bmatrix}+\begin{bmatrix}0&0\\3&-1\end{bmatrix}=\begin{bmatrix}1&2\\3&-1\end{bmatrix}
$$

用 $q=k_1=(1,0)$ 读： $S^\top q$ 就是 $S$ 的第 1 行 $(1,2)=v_1$ 。

再按原始公式直接算： $(q^\top k_1)v_1+(q^\top k_2)v_2=1\cdot v_1+0\cdot v_2=(1,2)$ 。两种算法结果一致。

这就是**联想记忆**：key 是地址，value 是内容；写入是累加外积，读出是拿 key 去查。

<div class="dg-flash"><div class="dg-q">上下文从 1 万涨到 100 万，线性注意力一个头的状态会变大多少？这省下来的东西，代价是什么？</div><div class="dg-a"><ul><li><b>结论</b>：一点也不变，始终是 d_k×d_v。代价是有损：100 万条 key-value 被压进 16384 个数里，不可能都存准。</li><li><b>为什么</b>：S 是所有外积的和，每次写入都叠加在同一块内存上，信息只会互相覆盖、混合。</li><li><b>例子</b>：2 维状态里只有 2 个互相正交的方向，第 3 条 key 必然和前两条有重叠，见下一节。</li></ul></div></div>

## 3 只加不减带来的两个毛病

**毛病 1：改不掉。** 假设 $k_1$ 对应的值更新了，要写入 $(k_1,(4,4))$ ：

$$
S=\begin{bmatrix}1&2\\3&-1\end{bmatrix}+\begin{bmatrix}4&4\\0&0\end{bmatrix}=\begin{bmatrix}5&6\\3&-1\end{bmatrix}
$$

再用 $k_1$ 读出 $(5,6)$ ，得到的是新旧值之和，而不是新值 $(4,4)$ 。

**毛病 2：串味。** 一般地，用某条 $k_j$ 去读：

$$
S^\top k_j=\sum_i (k_i^\top k_j)\,v_i=\underbrace{\lVert k_j\rVert^2 v_j}_{\text{想要的}}+\underbrace{\sum_{i\ne j}(k_i^\top k_j)\,v_i}_{\text{串进来的}}
$$

只有其他 key 都和 $k_j$ 正交时，读出才干净。但 $d_k$ 维空间里最多只有 $d_k$ 个互相正交的方向，长度 $T\gg d_k$ 时串味不可避免；而且只加不减，噪声会一直累积。

**手算 2。** 回到手算 1 的 $S=\begin{bmatrix}1&2\\3&-1\end{bmatrix}$ ，再写入 $k_3=(0.6,0.8)$ （已归一化）， $v_3=(0,5)$ ：

- 用 $k_1$ 读： $(1,2)+0.6\cdot(0,5)=(1,5)$ ，而 $k_1$ 的真值是 $(1,2)$ 。
- 用 $k_3$ 读： $0.6\cdot(1,2)+0.8\cdot(3,-1)+1\cdot(0,5)=(3,\,5.4)$ ，而 $k_3$ 的真值是 $(0,5)$ 。

**从优化的角度看**（Kimi Linear §2.2）：线性注意力这一步更新，等价于对目标 $\mathcal{L}(S)=-\langle S^\top k,\,v\rangle$ 做一步学习率为 1 的梯度下降。验证一下：

- 梯度是 $\partial\mathcal{L}/\partial S=-k v^\top$ 。
- 减去梯度，得到 $S+kv^\top$ ，正是线性注意力的更新。

这个目标**没有下界**： $S$ 和 $v$ 越对齐、越大，目标就越「好」。它完全不知道「这条已经存对了，不用再写」。毛病的根源就在这里。

<div class="dg-flash"><div class="dg-q">有人说：「把 d_k 从 128 加到 256 就能解决串味。」你同意吗？</div><div class="dg-a"><ul><li><b>结论</b>：只能缓解，解决不了。</li><li><b>为什么</b>：正交方向的个数从 128 涨到 256，但序列长度是几十万到一百万，T≫d_k 的关系不变；而且只加不减的写法没有改，噪声照样累积。</li><li><b>例子</b>：同一个 key 写两次值，读出的是两次值之和。这个问题与维度无关，换更新规则才能解决（下一节）。</li></ul></div></div>

## 4 Delta rule：先读，再只写误差

**想法**：写入之前，先看记忆里这个 key 现在存的是什么： $\hat v=S^\top k$ 。然后只把差值 $v-\hat v$ 写进去。

**推导。** 换一个有底的目标：让「拿 $k$ 读出来的值」尽量等于 $v$ ，即

$$
\mathcal{L}(S)=\tfrac12\lVert S^\top k-v\rVert^2=\tfrac12\sum_j\Big(\sum_i S_{ij}k_i-v_j\Big)^2
$$

对某一个元素 $S_{ij}$ 求导。只有第 $j$ 项含 $S_{ij}$ ，它的系数是 $k_i$ ：

$$
\frac{\partial\mathcal{L}}{\partial S_{ij}}=k_i\Big(\sum_{i'}S_{i'j}k_{i'}-v_j\Big)=k_i\,(\hat v-v)_j
\quad\Longrightarrow\quad
\nabla_S\mathcal{L}=k\,(\hat v-v)^\top
$$

以 $\beta_t$ 为学习率走一步：

$$
S_t=S_{t-1}-\beta_t k_t\,(S_{t-1}^\top k_t-v_t)^\top
$$

展开时注意 $k_t(S_{t-1}^\top k_t)^\top=k_t k_t^\top S_{t-1}$ ，于是

$$
S_t=(I-\beta_t k_t k_t^\top)\,S_{t-1}+\beta_t k_t v_t^\top
$$

这就是 DeltaNet 的更新式。所以**每处理一个 token，就在线训练一步「记忆」S**：写入就是一步梯度下降。这也是这类层被叫作「快权重」(fast weights) 的原因。

**手算 3：改写。** 状态仍是 $S=\begin{bmatrix}1&2\\3&-1\end{bmatrix}$ ，写入 $(k_1,(4,4))$ ， $\beta=1$ ：

1. 先读： $\hat v=S^\top k_1=(1,2)$ 。
2. 误差： $e=v-\hat v=(3,2)$ 。
3. 写入： $k_1e^\top=\begin{bmatrix}3&2\\0&0\end{bmatrix}$ ，所以 $S=\begin{bmatrix}4&4\\3&-1\end{bmatrix}$ 。

检查：用 $k_1$ 读出 $(4,4)$ ，是新值；用 $k_2$ 读出 $(3,-1)$ ，没被影响。

如果 $\beta=0.5$ ，第 1 行变成 $(1,2)+0.5\cdot(3,2)=(2.5,3)$ ，只往新值走了一半。 $\beta$ 就是**写入强度（学习率）**。K3 里它由当前 token 决定： $\beta_t=\mathrm{Sigmoid}(W_\beta x_t)$ ，模型自己判断这个 token 该写多重。

**手算 4：相近的 key。** 接着写入 $(k_3,v_3)=((0.6,0.8),(0,5))$ ， $\beta=1$ ：

1. 先读： $\hat v=0.6\cdot(4,4)+0.8\cdot(3,-1)=(4.8,\,1.6)$ 。
2. 误差： $e=(0,5)-(4.8,1.6)=(-4.8,\,3.4)$ 。
3. 写入： $k_3e^\top=\begin{bmatrix}-2.88&2.04\\-3.84&2.72\end{bmatrix}$ ，所以 $S=\begin{bmatrix}1.12&6.04\\-0.84&1.72\end{bmatrix}$ 。

检查：用 $k_3$ 读出 $0.6\cdot(1.12,6.04)+0.8\cdot(-0.84,1.72)=(0,5)$ ，正好存对。但用 $k_1$ 读出 $(1.12,6.04)$ ，不再是 $(4,4)$ 。

Delta rule **不能消灭串味**。它保证「当前这一条存准」，把代价按重叠程度 $k_i^\top k_3$ 分摊到相近的 key 上。和线性注意力相比，区别在于：它不会无限累积，存错的会在下次写入时被纠正。

**几何意义：只动 $k$ 这一个方向。** 设 $\lVert k\rVert=1$ ：

- 对 $k$ 本身： $(I-\beta kk^\top)k=k-\beta k(k^\top k)=(1-\beta)k$ 。
- 对任何垂直于 $k$ 的 $u$ ： $(I-\beta kk^\top)u=u$ ，不受影响。

所以这个矩阵只把 $k$ 方向上的旧内容缩到 $1-\beta$ 倍，其余方向原样保留。 $\beta=1$ 时它是投影，先把 $k$ 方向清零再写新值； $\beta=2$ 时它是 Householder 反射。论文称之为「广义 Householder 变换」。

**为什么 $k$ 必须 L2 归一化、 $\beta$ 必须在 (0,1)。** 一般情况下， $(I-\beta kk^\top)k=(1-\beta\lVert k\rVert^2)k$ ，所以 $k$ 方向的特征值是 $1-\beta\lVert k\rVert^2$ 。

- 不归一化时，取 $k=(1,1)$ ， $\lVert k\rVert^2=2$ ， $\beta=1.5$ ：特征值是 $1-3=-2$ 。每写一次，这个方向就放大 2 倍并翻号，几十步后数值溢出。
- 归一化后，特征值是 $1-\beta\in(0,1)$ ，永远不会放大。

这正是 K3 参数化（Eq.2）里 $q,k=\mathrm{L2Norm}(\cdot)$ 、 $\beta=\mathrm{Sigmoid}(\cdot)$ 的原因：它们不是随手加的，而是递推稳定的必要条件。

<div class="dg-flash"><div class="dg-q">如果有人把 β 的激活从 Sigmoid 换成 2·Sigmoid（范围变成 (0,2)），k 仍做 L2 归一化。会发生什么？是好是坏？</div><div class="dg-a"><ul><li><b>结论</b>：数值上仍然稳定，但 β&gt;1 时 k 方向的旧内容会被翻号，含义变成「过度纠正」。</li><li><b>为什么</b>：特征值 1−β∈(−1,1)，绝对值仍小于 1，不会发散；但负特征值意味着每写一次，该方向的残留就正负交替。</li><li><b>例子</b>：β=2 时变成 Householder 反射，k 方向的旧值被完整地取反保留，而不是被清掉。DeltaProduct 一类工作正是利用负特征值来提升状态追踪能力。</li></ul></div></div>

## 5 遗忘：从一个 α 到每个通道一个 α

Delta rule 只修改 $k$ 方向。与新 key 无关的旧内容会一直留在状态里：一本书前半部分的细节，不会因为读到后面就自己淡出。所以需要遗忘。

**Gated DeltaNet（GDN）**：每一步先把整个状态乘一个标量 $\alpha_t\in(0,1)$ ：

$$
S_t=\alpha_t\,(I-\beta_t k_t k_t^\top)\,S_{t-1}+\beta_t k_t v_t^\top
$$

Kimi Linear 把它解释为对快权重 $S$ 做 weight decay：每一步把所有记忆按比例缩一点。

**KDA**：把标量换成对角矩阵 $\mathrm{Diag}(\alpha_t)$ ，其中 $\alpha_t\in(0,1)^{d_k}$ ，并且**先衰减，再在衰减后的状态上做 delta**：

$$
S_t=(I-\beta_t k_t k_t^\top)\,\mathrm{Diag}(\alpha_t)\,S_{t-1}+\beta_t k_t v_t^\top
$$

所以这时读出的旧值是 $\hat v=(\mathrm{Diag}(\alpha_t)S_{t-1})^\top k_t$ 。

由第 0 节的行视角， $\mathrm{Diag}(\alpha)S$ 就是**把第 $i$ 行乘以 $\alpha_i$** 。每个 key 通道各有自己的遗忘速度。

**手算 5。** 取 $\alpha=(0.5,\,1)$ ，作用在手算 3 的结果 $S=\begin{bmatrix}4&4\\3&-1\end{bmatrix}$ 上：

$$
\mathrm{Diag}(\alpha)S=\begin{bmatrix}2&2\\3&-1\end{bmatrix}
$$

通道 1 一步就忘掉一半，通道 2 原样保留。

**用半衰期来感受 α。** 一个通道保持 $\alpha$ 不变时，经过 $n$ 步只剩 $\alpha^n$ 。剩一半所需的步数为 $n_{1/2}=\ln 2/(-\ln\alpha)$ ：

| $\alpha$ | 0.5 | 0.9 | 0.99 | 0.999 |
|-|-|-|-|-|
| 半衰期（token） | 1 | 6.6 | 69 | 693 |

128 个通道可以同时有「几个 token 就忘」和「几百个 token 还记得」的通道；标量 α 只能让全部通道用同一速度。这就是 KDA 名字里 「fine-grained」（细粒度）的含义。

**衰减本身就是位置编码。** 先忽略 $\beta$ 项，只看衰减，把递推展开：第 $i$ 步写入的 $k_iv_i^\top$ ，到第 $t$ 步时被乘了 $\alpha_{i+1},\dots,\alpha_t$ 。记 $\gamma^{i\to t}=\prod_{j=i+1}^{t}\alpha_j$ （逐通道相乘），则

$$
o_t^\top=\sum_{i\le t} q_t^\top\,\mathrm{Diag}(\gamma^{i\to t})\,k_i\;v_i^\top
$$

$q$ 和 $k$ 之间插进了一个随距离（以及内容）变化的对角矩阵。RoPE 做的也是在 $q$ 、 $k$ 之间插一个只依赖距离的矩阵，只不过它是旋转矩阵：正交，模恒为 1。KDA 把它换成模小于 1、由数据决定的对角阵。Kimi Linear 称之为「放松了 RoPE 的正交约束的乘性位置编码」。

这直接决定了 K3 的一个设计：**MLA 层用 NoPE（不加位置编码）**，位置信息全由 KDA 层的衰减提供。所以 K3 训练到 1M 上下文时，不需要 YaRN 这类 RoPE 外推技巧。

**K3 里每一项怎么算出来**（K3 Eq.2、Eq.5）：

| 量 | 计算 | 为什么这样设计 |
|-|-|-|
| $q_t,k_t$ | $\mathrm{L2Norm}(\mathrm{Swish}(\mathrm{ShortConv}(Wx_t)))$ | L2Norm 保证第 4 节的稳定性；短卷积补充局部信息 |
| $v_t$ | $\mathrm{Swish}(\mathrm{ShortConv}(W_vx_t))$ | 不需要归一化 |
| $\beta_t$ | $\mathrm{Sigmoid}(W_\beta x_t)$ | 落在 (0,1) |
| $z_t$ | $W_\alpha^{\uparrow}W_\alpha^{\downarrow}x_t+b_\alpha$ | 每头要 $d_k$ 个门值，用低秩投影省参数 |
| $g_t$ | $g_{\min}\cdot\mathrm{Sigmoid}(e^{A_h}z_t)$ ， $g_{\min}=-5$ | 对数衰减落在 (−5, 0) |
| $\alpha_t$ | $\exp(g_t)$ | 落在 $(e^{-5},1)\approx(0.0067,\,1)$ |

为什么偏偏要给 $g$ 加 −5 的下界？这要等到下一节看训练怎么并行才能讲清。

<div class="dg-flash"><div class="dg-q">一个 key 通道学到 α≈0.3，另一个学到 α≈0.998。你猜它们各自在记什么样的信息？如果把 KDA 换回 GDN（标量 α），模型会损失什么？</div><div class="dg-a"><ul><li><b>结论</b>：α≈0.3 的通道只记最近一两个 token，像局部语法和词形；α≈0.998 的通道能记几百个 token，像段落主题和实体。换成 GDN 后，一层只能选一个速度。</li><li><b>为什么</b>：半衰期 ln2/(−lnα)：0.3 对应约 0.6 个 token，0.998 对应约 346 个 token。</li><li><b>例子</b>：GDN 想同时保留长程信息，就得让 α 整体接近 1，局部噪声因此也清不掉；KDA 可以分通道各自处理。</li></ul></div></div>

## 6 训练怎么并行：分块算法手推

递推式是串行的：1M 个 token 要一步接一步地算，每步只是一个很小的 $d_k\times d_v$ 更新，GPU 的矩阵乘单元（Tensor Core）根本用不上。办法是**分块（chunkwise）**：

- 把序列切成长度为 $C$ 的块（Kimi Linear 取 $C=64$ ）。
- 块内用矩阵乘并行算，块与块之间仍然递推。串行步数从 $T$ 降到 $T/C$ 。

### 6.1 先推不带衰减的 delta（核心）

设 $S^0$ 是进入本块时的状态，块内 token 编号为 $r=1,\dots,C$ 。把「乘过 $\beta$ 的误差」记为 $\tilde e_r=\beta_r\,(v_r-S^{r-1\top}k_r)$ ，于是每步更新是 $S^r=S^{r-1}+k_r\tilde e_r^\top$ 。从块首累加：

$$
S^{r-1}=S^0+\sum_{i<r}k_i\tilde e_i^\top
$$

代回误差的定义：

$$
\tilde e_r=\beta_r\Big(v_r-S^{0\top}k_r-\sum_{i<r}(k_i^\top k_r)\,\tilde e_i\Big)
$$

可以看到：块内第 $r$ 个 token 的误差，依赖块内前面所有 token 的误差，因为前面的写入改变了它读到的旧值。把和式移到左边：

$$
\tilde e_r+\beta_r\sum_{i<r}(k_r^\top k_i)\,\tilde e_i=\beta_r\,(v_r-S^{0\top}k_r)
$$

把 $C$ 个 token 按行堆起来： $K$ 是 $C\times d_k$ 、第 $r$ 行为 $k_r^\top$ ； $V$ 、 $\tilde E$ 同理。这 $C$ 个方程合成一个矩阵方程：

$$
\big(I+\mathrm{StrictTril}(\mathrm{Diag}(\beta)\,KK^\top)\big)\,\tilde E=\mathrm{Diag}(\beta)\,(V-KS^0)
$$

左边是**对角线为 1 的下三角矩阵**，用前代法从第 1 行往下逐行解即可，不需要一般的矩阵求逆。记

$$
M=\big(I+\mathrm{StrictTril}(\mathrm{Diag}(\beta)KK^\top)\big)^{-1}\mathrm{Diag}(\beta),\qquad U=MV,\qquad W=MK
$$

就得到 $\tilde E=U-WS^0$ 。这正是论文里的「伪值」 $\tilde V=U-WS$ 。求 $U$ 、 $W$ 的这一步叫 **UT 变换**。

它的价值在于： **$U$ 、 $W$ 只依赖本块的 $K$ 、 $V$ 、 $\beta$ ，与 $S^0$ 无关**。所以所有块可以同时把它们算好，只有 $-WS^0$ 这一项要等前一块的状态。

有了 $\tilde E$ ，输出和下一块的状态都是矩阵乘：

$$
O=QS^0+\mathrm{Tril}(QK^\top)\,\tilde E,\qquad S^C=S^0+K^\top\tilde E
$$

推导：第 $r$ 个输出 $o_r=S^{r\top}q_r=S^{0\top}q_r+\sum_{i\le r}(k_i^\top q_r)\,\tilde e_i$ 。这里用 Tril（保留对角线），因为第 $r$ 个输出读的是写入第 $r$ 个 token **之后**的状态。

**手算 6：把第 4 节的两步改成一个块来算，看结果是否一致。**

- $S^0=\begin{bmatrix}1&2\\3&-1\end{bmatrix}$ 。
- 块内两个 token： $(k_1,(4,4))$ 和 $(k_3,(0,5))$ ，都取 $\beta=1$ 。

1. 右边：
   - 第 1 行 $(4,4)-k_1^\top S^0=(4,4)-(1,2)=(3,2)$ 。
   - 第 2 行 $(0,5)-k_3^\top S^0=(0,5)-(3.0,\,0.4)=(-3,\,4.6)$ 。
2. 左边：严格下三角只有一个元素 $k_3^\top k_1=0.6$ 。
3. 前代：
   - $\tilde e_1=(3,2)$ 。
   - $\tilde e_2=(-3,4.6)-0.6\cdot(3,2)=(-4.8,\,3.4)$ 。

   这与手算 3、4 里逐步算出的误差完全相同。
4. 新状态： $S^C=S^0+k_1\tilde e_1^\top+k_3\tilde e_2^\top=\begin{bmatrix}1.12&6.04\\-0.84&1.72\end{bmatrix}$ 。这与手算 4 的结果一致。

### 6.2 加上逐通道衰减

衰减后，「第 $i$ 个 token 写的内容被第 $r$ 个 token 读到」要乘上 $\mathrm{Diag}(\gamma^{i\to r})$ 。记块内的累积衰减为 $\gamma^r=\prod_{j\le r}\alpha_j$ ，则 $\gamma^{i\to r}=\gamma^r/\gamma^i$ 。

关键在于把这个比值**拆成两个因子，分别乘到 $q$ 和 $k$ 上**：

$$
q_r^\top\mathrm{Diag}(\gamma^r/\gamma^i)\,k_i=(q_r\odot\gamma^r)^\top(k_i/\gamma^i)
$$

拆开以后，整块仍然是一次矩阵乘。 $\Gamma$ 把 $\gamma^1,\dots,\gamma^C$ 按行堆起来，得到 K3 Eq.4：

$$
A=\mathrm{Tril}\big[(Q\odot\Gamma)(K/\Gamma)^\top\big],\qquad O=(\Gamma\odot Q)\,S^0+A\,(U-WS^0)
$$

UT 变换里的 $KK^\top$ 也相应换成 $(\Gamma\odot K)(K/\Gamma)^\top$ 。块间状态更新为

$$
S^{C}=\mathrm{Diag}(\gamma^C)\,S^0+(\Gamma^{i\to C}\odot K)^\top(U-WS^0)
$$

它的结构和 6.1 完全相同，只是多了衰减因子。

### 6.3 为什么 K3 要给衰减加 −5 的下界

注意 $K/\Gamma$ 里的 **$1/\gamma^i$** 。 $\gamma^i$ 是一串 $(0,1)$ 之间的数相乘，只要某个通道学到一个极小的 $\alpha$ （比如 $10^{-20}$ ）， $1/\gamma$ 就会在有限精度下溢出。

- **Kimi Linear 的做法**：在对数空间算相对衰减，并把每个块再切成 16-token 的小 tile。
  - 非对角 tile 可以直接做稠密矩阵乘。
  - 对角 tile 要逐个位置对显式计算 $\exp(\log\gamma^r-\log\gamma^i)$ ，不能用 Tensor Core。K3 原文说这是「块内的主要瓶颈」。
- **K3 的做法**： $g>-5$ ，所以 16 个 token 的累积对数衰减大于 $16\times(-5)=-80$ ，倒数小于 $e^{80}\approx5.5\times10^{34}$ ，而 BF16 的最大值约 $3.4\times10^{38}$ 。数值有界，对角 tile 也能做稠密矩阵乘，逐位置对的计算路径被整个删掉了。

**代价**：单步保留率不能低于 0.0067。<span class="judge">解读者判断</span> 这个限制几乎不损失表达力：保留 0.0067 已经接近清零，连续两步就只剩 $4.5\times10^{-5}$ 。用一个几乎用不到的取值范围，换来整个内核走 Tensor Core。

K3 还有一处小改动：输出门从 Kimi Linear 的低秩 $W_g^{\uparrow}W_g^{\downarrow}$ 改为全秩， $y=W_o[\mathrm{Sigmoid}(W_gx)\odot\mathrm{RMSNorm}(\tilde o)]$ 。

<div class="dg-flash"><div class="dg-q">如果把块长 C 从 64 改成 256，同时把 g_min 放宽到 −10，K3 现在「对角 tile 全走 Tensor Core」的结论还成立吗？你会怎么改？</div><div class="dg-a"><ul><li><b>结论</b>：取决于 tile 长度，而不是块长。tile 仍是 16 时，最坏累积对数衰减为 −160，e^160≈3×10^69，远超 BF16 范围，结论不再成立。</li><li><b>为什么</b>：倒数的上界是 e^(−g_min×tile 长度)，要保持在 BF16 范围（约 e^88）以内，需要 g_min×tile 长度 ≥ −88 左右。</li><li><b>例子</b>：g_min=−10 时，tile 要缩到 8 个 token（−80）才回到安全区；tile 越小，矩阵乘越碎，效率越低。所以 −5 × 16 是一个取舍。</li></ul></div></div>

## 7 为什么还要留 1/4 的全注意力

前面的推导一直在说同一件事：**固定大小的状态是有损压缩**。一个头 16384 个数，最多只有 $d_k=128$ 个互相正交的「槽位」能精确存取。「从一百万个 token 里精确找回第 37 万个 token 附近的那个编号」这类任务，只靠 KDA 必然吃亏。Kimi Linear 用回文、MQAR（多查询联想召回）、状态追踪等合成任务测过这类能力。

所以 K3 用**混合**结构：

- **层数**：69 层 KDA + 24 层 Gated MLA。也就是 23 组「3 层 KDA + 1 层 MLA」，末尾再加 1 层 MLA。
- **分工**：KDA 层负责局部和「有状态」的信息，并提供位置信号；MLA 层负责全局的精确召回。
- **推理**：只有 MLA 层有 KV cache，KDA 层只有固定大小的状态。

Kimi Linear 在 3:1 配置下的公开数字：

- KV cache 最多省 75%。
- 1M 上下文解码每 token 耗时 1.84 ms，全 MLA 是 11.48 ms，快 6.3 倍。
- RULER 128k 得 84.3。

其他家走的是同一思路，只是递推层不同：Qwen3-Next / Qwen3.5 一线用 Gated DeltaNet（即第 5 节的标量 α 版本）与门控注意力混合；Nemotron 系列用 Mamba 类 SSM 层与注意力混合。

**仍然开放的难点：**

1. **比例怎么定**。3:1 是实验调出来的取舍，不同任务的最优比例不同，目前没有理论。
2. **前缀缓存**。KV cache 可以按 token 截断复用，KDA 状态却是整个前缀压出来的一个矩阵，没法截断。K3 §5.4.1 的做法是在块边界存状态，即「状态感知的前缀缓存」。
3. **序列并行**。块与块之间仍然要串行递推，超长序列切到多卡上时，需要专门的 KDA Context Parallelism（K3 §5.1）。

<div class="dg-flash"><div class="dg-q">你要给一个「读完整个代码仓库再回答问题」的 Agent 选基座。候选 A 是全 KDA（没有全注意力层），候选 B 是 K3 式 3:1 混合。只看本节内容，你选哪个？为什么？</div><div class="dg-a"><ul><li><b>结论</b>：选 B。</li><li><b>为什么</b>：读代码要精确召回某个函数名、某行配置，属于联想召回任务；全 KDA 的状态容量有限，且相近的 key 会互相干扰（第 3、4 节），而 MLA 层能精确回看。</li><li><b>例子</b>：同一个变量名在几十个文件里出现，key 高度相似；按手算 4，delta rule 会让这些相似的 key 互相改写。</li><li><b>用到项目</b>：评测长上下文模型时，要专门放「精确找回」类用例（如 MQAR、needle），不能只看困惑度。</li></ul></div></div>

## 8 之后的改进与同类方案对比

前 7 节把 KDA 推出来了。这一节回答两个问题：同一个问题别人怎么解；KDA 之后还在往哪改。

### 8.1 一张 2×2 表：门控粒度 × 写入方式

第 2–5 节其实只动了两个开关：**遗忘是标量还是逐通道**、**写入是直接加还是只写误差**。把已有模型放进这两个开关组成的格子里：

| | 直接加： $+k_t v_t^\top$ | 只写误差（delta）： $+\beta_t k_t(v_t-\hat v_t)^\top$ |
|-|-|-|
| 标量遗忘 $\alpha_t$ | Mamba2（2024-05）、RetNet（固定 α） | Gated DeltaNet（2024-12），Qwen3-Next 采用 |
| 逐通道遗忘 $\mathrm{Diag}(\alpha_t)$ | GLA（2023-12） | **KDA**（2025-10），K3 采用 |

<span class="judge">解读者判断</span> 所以 KDA 可以看成「GLA 的逐通道门 + DeltaNet 的误差写入」。下面用同一个输入把四格都算一遍，看两个开关各自管什么。

**手算 5：四种规则写同一个 (k, v)。** 起点用手算 1 的状态 $S=\begin{bmatrix}1&2\\3&-1\end{bmatrix}$ ，也就是 $k_1$ 存着 $(1,2)$ ， $k_2$ 存着 $(3,-1)$ 。现在写入 $k=k_1=(1,0)$ 、 $v=(4,4)$ ， $\beta=1$ 。标量遗忘取 $\alpha=0.5$ ，逐通道遗忘取 $\alpha=(0.5,1)$ ，即只让第 1 个通道遗忘。

| 规则 | 衰减后 | 写入 | 结果 S | 读 $k_1$ | 读 $k_2$ |
|-|-|-|-|-|-|
| Mamba2 | 两行都乘 0.5 | 加 $k v^\top$ | $\begin{bmatrix}4.5&5\\1.5&-0.5\end{bmatrix}$ | (4.5, 5) | (1.5, −0.5) |
| GLA | 只第 1 行乘 0.5 | 加 $k v^\top$ | $\begin{bmatrix}4.5&5\\3&-1\end{bmatrix}$ | (4.5, 5) | (3, −1) |
| Gated DeltaNet | 两行都乘 0.5 | 读出 (0.5, 1)，写误差 (3.5, 3) | $\begin{bmatrix}4&4\\1.5&-0.5\end{bmatrix}$ | (4, 4) | (1.5, −0.5) |
| KDA | 只第 1 行乘 0.5 | 读出 (0.5, 1)，写误差 (3.5, 3) | $\begin{bmatrix}4&4\\3&-1\end{bmatrix}$ | (4, 4) | (3, −1) |

检查：

- **列方向看写入方式**。两种「直接加」读 $k_1$ 都是 (4.5, 5)，旧值残留没清干净；两种 delta 都精确等于 (4, 4)。
- **行方向看遗忘粒度**。两种标量遗忘把和本次写入无关的 $k_2$ 也砍成一半；两种逐通道遗忘让 $k_2$ 原样保留。
- 只有 KDA 同时做到「改写干净」和「不误伤无关记忆」。这就是它比 GDN 多出的那一点。

<div class="dg-flash"><div class="dg-q">如果一个任务里所有信息的「保鲜期」都差不多（比如固定窗口内的局部语法），逐通道遗忘还值得它多出来的参数和内核复杂度吗？</div><div class="dg-a"><ul><li><b>结论</b>：收益会变小，标量门的 GDN 可能就够了。</li><li><b>为什么</b>：逐通道门的价值在于让不同通道有不同半衰期；所有信息半衰期相同时，最优的 α 各通道都一样，退化成标量门。</li><li><b>例子</b>：手算 5 里如果 k₂ 本来也该忘，GDN 和 KDA 的结果就没有区别。</li><li><b>用到项目</b>：做消融时要用长短依赖混合的任务，否则测不出这类改进。</li></ul></div></div>

### 8.2 改进方向一：让转移矩阵更有表达力

第 4 节为了稳定，要求 $\beta\in(0,1)$ ，于是 $(I-\beta kk^\top)$ 在 $k$ 方向的特征值 $1-\beta$ 落在 (0,1)。这条限制有代价。

<span class="fact">源文事实</span> Grazzi 等人（arXiv 2411.12537，2024-11，ICLR 2025）指出：转移矩阵的特征值全为非负时，线性 RNN 在有限精度下做不了「奇偶校验」这类状态追踪任务。把 $\beta$ 的范围放宽到 $(0,2)$ ，特征值 $1-\beta$ 就能取到 (−1, 1)，问题得到解决。这时 $\lvert 1-\beta \rvert<1$ ，递推仍然不发散。

**手算 6：负特征值怎么做奇偶校验。** 用 1 维状态 $s$ ，初值 1。读到比特 1 时取 $\beta=2$ ，转移是 $1-2=-1$ ；读到 0 时取 $\beta=0$ ，转移是 1。输入 1, 0, 1, 1：

- $s=1\to-1$ （读 1）
- $\to-1$ （读 0，不变）
- $\to1$ （读 1）
- $\to-1$ （读 1）

检查：结果 −1 表示 1 的个数是奇数（这里是 3 个）。2 维时 $k=(1,0)$ 、 $\beta=2$ ， $I-2kk^\top=\mathrm{diag}(-1,1)$ ，就是把第 1 个通道翻号的反射。如果特征值只能在 (0,1)，状态只会缩小，翻不了号。

<span class="fact">源文事实</span> 沿这个方向还有两个代表工作：

- **DeltaProduct**（arXiv 2502.10297，2025-02）：每个 token 做 $n_h$ 次 delta 更新，转移矩阵是 $n_h$ 个广义 Householder 矩阵的乘积。 $n_h$ 越大，状态追踪越强，代价是计算按 $n_h$ 倍增加。
- **RWKV-7「Goose」**（arXiv 2503.14456，2025-03）：同样是广义 delta rule。衰减是逐通道向量，「学习率」 $\beta$ 也变成逐通道向量，并且把「擦除用的 key」和「写入用的 key」分开。

### 8.3 改进方向二：把记忆从矩阵换成网络

第 4 节说过，delta rule 就是对 $\tfrac12\lVert S^\top k-v \rVert^2$ 做一步在线梯度下降。也就是说，状态 $S$ 本身是一个线性回归模型，每读一个 token 就训练一步。

<span class="judge">解读者判断</span> 顺着这个视角，自然的下一步是把「线性模型」换成更强的模型。

- <span class="fact">源文事实</span> **TTT**（Sun 等，arXiv 2407.04620，2024-07）把隐状态换成一个小 MLP，推理时对自监督损失做梯度更新。
- <span class="fact">源文事实</span> **Titans**（Google，arXiv 2501.00663，2024-12）用深层 MLP 做长期记忆，加入动量和遗忘，并和注意力组合使用。

代价也来自同一个地方：记忆不再是矩阵，就没法像第 6 节那样整理成大块矩阵乘法。这类方法目前更多停留在研究阶段，尚未成为前沿大模型的主干层。

### 8.4 另一条路：不压缩，只少读（稀疏注意力）

线性注意力用「压缩」换效率。另一条路是保留全部 KV，但每步只读一部分。

| 维度 | 线性注意力 / KDA | 稀疏注意力（如 DeepSeek NSA 2025-02、DSA 2025-09） | 全注意力 |
|-|-|-|-|
| 每步存储 | 固定状态，与长度无关 | 全部 KV，随长度线性增长 | 全部 KV |
| 每步计算 | 常数 | 只算选中的 k 个 token | 和长度成正比 |
| 精确召回 | 有损，靠混合层补 | 选对了就精确，选错了就丢 | 精确 |
| 主要风险 | 状态容量、串味 | 选择器漏选 | 成本 |

<span class="judge">解读者判断</span> 两条路并不互斥：K3 这类模型用 KDA 省存储，在保留的全注意力层上仍可叠加稀疏化来省计算。

### 8.5 反例：有团队试过又退回全注意力

<span class="fact">源文事实</span> MiniMax-01（2025-01）用 lightning attention（一种不带 delta 的线性注意力），每 7 层线性层配 1 层 softmax 注意力。到 MiniMax-M2（2025-10），团队改回全注意力。按团队的公开说明，原因是高效注意力在复杂多跳推理和 Agent 任务上暴露出短板，而且当时的评测和基础设施还不足以把这些短板测清楚。（具体措辞以原文为准，待核实。）

<span class="judge">解读者判断</span> 这说明两件事：

1. 混合架构的收益依赖**递推层本身够强**。不带 delta、不带细粒度遗忘的线性层，更容易在召回和推理上吃亏，这正是第 3–5 节修掉的缺陷。
2. **短上下文、短任务的评测会掩盖问题**。判断一个线性 / 混合模型时，要看长上下文的精确召回和多跳推理，不能只看困惑度和常规榜单。

### 8.6 怎么选：一张判断清单

遇到一篇新的「高效注意力」论文或新模型时，按顺序问：

1. **它压缩还是只少读**？压缩的看状态大小和遗忘机制；只少读的看选择器怎么选、漏选了怎么办。
2. **写入是加法还是 delta**？只做加法的，先怀疑它的召回能力（手算 2、手算 5）。
3. **遗忘是什么粒度**？标量、逐通道，还是逐元素。
4. **转移矩阵的特征值范围**？只在 (0,1) 内的，状态追踪会受限（手算 6）。
5. **能不能分块并行、能不能全走 Tensor Core**？不能的，训练成本会限制它上规模（第 6 节）。
6. **混合比例和精确召回的证据**？看有没有 MQAR、RULER、needle 这类测试，以及和同规模全注意力模型的对比。

## 动手：在 2×2 状态上试三种更新规则

<div class="dg-widget" data-src="widgets/delta_state.html" data-height="420" data-title="选更新规则，写入 (k,v)，观察状态和三个探针 key 的读出"></div>

建议按这个顺序试：

1. 点「载入本节例子」，状态变成手算 1 的结果。
2. 用「线性注意力」写入 $(k_1,(4,4))$ ，看 $k_1$ 读出 $(5,6)$ 。
3. 重置，改用「Delta」再写一次，看读出变成 $(4,4)$ 。
4. 切到「KDA」，把 $\alpha_1$ 调到 0.5，连写几次，看第 1 行怎样衰减。

## 回到原章

这一节展开的是第 140 章「预训练·结构」里「长」那一条路线中的 KDA。回到原章时，可以用本节的推导链去对照其他「长」方案：

- **CSA/HCA、MSA 一类稀疏注意力**：保留全部 KV，每步只挑一部分来读。省的是计算，不省存储。
- **KDA、Gated DeltaNet 一类线性注意力**：直接把 KV 压成固定状态。省存储也省计算，代价是有损。

读原章里的配置表时，可以试着自己问：这一层的状态多大？靠什么遗忘？精确召回交给哪一层？

## 延伸阅读

- [Kimi K3 Technical Report §2.1.1](https://arxiv.org/abs/2607.24653)（2026-07）：KDA 的最新形式。重点读 Eq.1–5 和下界衰减一段，再看 §5.1 的 FlashKDA 内核、§5.4.1 的前缀缓存。
- [Kimi Linear](https://arxiv.org/abs/2510.26692)（2025-10）：§2.2 是本节第 2–5 步推导的原文，§3.1 是完整的分块和 UT 变换，§6.3 是复杂度公式。
- [Parallelizing Linear Transformers with the Delta Rule over Sequence Length](https://arxiv.org/abs/2406.06484)（2024，经典锚点）：DeltaNet 分块并行和 WY 表示的出处，想彻底弄懂 6.1 节就读它的 §3。
- [Gated Delta Networks](https://arxiv.org/abs/2412.06464)（2024，经典锚点）：GDN 的原文，看标量门控和 delta 怎样结合。
- [Gated Linear Attention](https://arxiv.org/abs/2312.06635)（2023-12）：逐通道遗忘门的来源，对照 8.1 的表看它和 KDA 只差 delta 写入。
- [Unlocking State-Tracking in Linear RNNs Through Negative Eigenvalues](https://arxiv.org/abs/2411.12537)（2024-11）：8.2 负特征值的出处。
- [DeltaProduct](https://arxiv.org/abs/2502.10297)（2025-02）、[RWKV-7](https://arxiv.org/abs/2503.14456)（2025-03）：广义 delta rule 的两种做法。
- [Titans](https://arxiv.org/abs/2501.00663)（2024-12）：把记忆换成深层网络，8.3 的代表。
- [flash-linear-attention](https://github.com/fla-org/flash-linear-attention)：这些层的开源 Triton 实现，KDA 的内核也在里面，适合对照公式读代码。
