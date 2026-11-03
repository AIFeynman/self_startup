# 混合专家 MoE 研究脉络

MoE主题旨在解决大模型容量与计算成本之间的矛盾：通过稀疏路由让每个token只激活少量专家，在保持推理成本可控的同时大幅扩展参数量。技术演进经历三个阶段：早期自适应混合专家与分层MoE奠定门控路由框架；2017年稀疏门控MoE层与GShard/Switch Transformer将MoE推向百亿至万亿参数，并解决负载均衡与训练稳定性；2022年后DeepSeekMoE、Mixtral等推动专家细粒度化、共享专家与无辅助损失均衡，同时系统与推理优化（DeepSpeed-MoE、MegaBlocks、REAP）使MoE成为主流大模型架构。

**前置基础**：[Adaptive Mixtures of Local Experts](https://www.semanticscholar.org/paper/c8d90974c3f3b40fa05e322df2905fc16204aa56)（1991，被引 7,382）；[Hierarchical Mixtures of Experts and the EM Algorithm](https://www.semanticscholar.org/paper/f6d8a7fc2e2d53923832f9404376512068ca2a57)（1993，被引 3,885）；[Estimating or Propagating Gradients Through Stochastic Neurons for Conditional Computation](https://arxiv.org/abs/1308.3432)（2013，被引 4,473）；[Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)（2015，被引 27,519）；[Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）；[Adam: A Method for Stochastic Optimization](https://arxiv.org/abs/1412.6980)（2014，被引 174,688）

## 稀疏门控与路由演进

从自适应混合专家出发，稀疏门控MoE层首次将MoE落地到大规模语言模型，Switch Transformer简化top-1路由并提升稳定性，专家选择路由与细粒度专家分割进一步促进专家专业化与负载均衡。

- **起点** [Adaptive Mixtures of Local Experts](https://www.semanticscholar.org/paper/c8d90974c3f3b40fa05e322df2905fc16204aa56)（1991，被引 7,382）：提出门控网络为每个样本选择专家子网络，奠定MoE基本框架
- **改进** [Hierarchical Mixtures of Experts and the EM Algorithm](https://www.semanticscholar.org/paper/f6d8a7fc2e2d53923832f9404376512068ca2a57)（1993，被引 3,885）：将MoE扩展为分层树状结构并用EM算法训练
- **里程碑** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：提出稀疏门控MoE层，实现137B参数条件计算
- **里程碑** [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)（2021，被引 5,265）：简化top-1路由并改进训练稳定性，扩展至万亿参数
- **变体** [Mixture-of-Experts with Expert Choice Routing](https://arxiv.org/abs/2202.09368)（2022，被引 984）：让专家选择top-k token，实现负载均衡与可变路由
- **改进** [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)（2024，被引 1,277）：细粒度专家分割与共享专家隔离，促进专家专业化
- **最新** [Demons in the Detail: On Implementing Load Balancing Loss for Training Specialized Mixture-of-Expert Models](https://arxiv.org/abs/2501.11873)（2025，被引 71）：用global-batch负载均衡损失避免micro-batch抑制专家专业化

## 大规模MoE模型与训练

GShard解决超大MoE的自动分片与编程难题，GLaM验证稀疏MoE在语言模型上的能效优势，DeepSeek系列与Mixtral将MoE推向开源前沿，Qwen3与gpt-oss进一步融合推理与MoE架构。

- **起点** [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668)（2020，被引 2,554）：提出GShard自动分片，将MoE多语翻译扩至6000亿参数
- **里程碑** [GLaM: Efficient Scaling of Language Models with Mixture-of-Experts](https://arxiv.org/abs/2112.06905)（2021，被引 1,379）：GLaM 1.2T参数，训练能耗仅为GPT-3的1/3
- **里程碑** [Mixtral of Experts](https://arxiv.org/abs/2401.04088)（2024，被引 2,263）：Mixtral 8x7B开源稀疏MoE，性能匹配Llama 2 70B
- **改进** [DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model](https://arxiv.org/abs/2405.04434)（2024，被引 1,589）：DeepSeek-V2用MLA压缩KV cache，训练省42.5%
- **里程碑** [DeepSeek-V3 Technical Report](https://www.semanticscholar.org/paper/5b6fdb2aea424d02c141da81d62b04d739d62b96)（2024，被引 4,377）：DeepSeek-V3采用无辅助损失负载均衡与FP8训练
- **最新** [Qwen3 Technical Report](https://arxiv.org/abs/2505.09388)（2025，被引 9,881）：Qwen3统一思考/非思考模式并引入thinking budget
- **最新** [gpt-oss-120b&gpt-oss-20b Model Card](https://arxiv.org/abs/2508.10925)（2025，被引 1,613）：gpt-oss开放权重MoE推理模型，经蒸馏与RL训练

## MoE训练稳定性与均衡

针对稀疏专家模型训练不稳定、负载不均与路由崩溃问题，ST-MoE提出router z-loss与专家dropout，R3对齐训练与推理路由以稳定RL，global-batch均衡损失进一步促进专家专业化。

- **起点** [ST-MoE: Designing Stable and Transferable Sparse Expert Models](https://arxiv.org/abs/2202.08906)（2022，被引 506）：提出router z-loss与专家dropout，稳定稀疏专家训练
- **改进** [Demons in the Detail: On Implementing Load Balancing Loss for Training Specialized Mixture-of-Expert Models](https://arxiv.org/abs/2501.11873)（2025，被引 71）：用global-batch负载均衡损失避免micro-batch抑制专业化
- **最新** [Stabilizing MoE Reinforcement Learning by Aligning Training and Inference Routers](https://arxiv.org/abs/2510.11370)（2025，被引 86）：R3回放推理路由分布，解决MoE RL训练崩溃

## MoE系统与推理优化

MoE的稀疏计算带来显存、通信与推理效率挑战。DeepSpeed-MoE提供端到端训练推理方案，MegaBlocks用块稀疏kernel避免丢token，REAP剪枝压缩专家，PagedAttention与FlashAttention优化推理与注意力。

- **起点** [DeepSpeed-MoE: Advancing Mixture-of-Experts Inference and Training to Power Next-Generation AI Scale](https://arxiv.org/abs/2201.05596)（2022，被引 703）：DeepSpeed-MoE端到端方案，推理延迟降7.3倍
- **改进** [MegaBlocks: Efficient Sparse Training with Mixture-of-Experts](https://arxiv.org/abs/2211.15841)（2022，被引 302）：MegaBlocks块稀疏kernel，不丢token且训练加速
- **改进** [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)（2023，被引 9,724）：PagedAttention实现KV cache近零浪费，提升吞吐
- **改进** [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)（2022，被引 5,766）：FlashAttention IO感知分块，训练提速2-3倍
- **改进** [FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning](https://arxiv.org/abs/2307.08691)（2023，被引 3,589）：FlashAttention-2优化工作划分，达A100理论FLOPs的50-73%
- **最新** [REAP the Experts: Why Pruning Prevails for One-Shot MoE compression](https://arxiv.org/abs/2510.13999)（2025，被引 66）：REAP剪枝准则压缩MoE，50%压缩下代码生成近乎无损

## MoE多模态与视觉扩展

将MoE稀疏思想扩展到视觉与多模态领域。V-MoE验证视觉MoE可行性，LIMoE用熵正则稳定多模态专家均衡，MoE-LLaVA解决LLM转稀疏LVLM训练崩溃，Kimi-VL与MoETok进一步推动高效多模态MoE。

- **起点** [Scaling Vision with Sparse Mixture of Experts](https://arxiv.org/abs/2106.05974)（2021，被引 1,267）：V-MoE将ViT稀疏化为专家混合，推理算力减半
- **改进** [Multimodal Contrastive Learning with LIMoE: the Language-Image Mixture of Experts](https://arxiv.org/abs/2206.02770)（2022，被引 372）：LIMoE用熵正则稳定多模态专家均衡
- **改进** [MoE-LLaVA: Mixture of Experts for Large Vision-Language Models](https://arxiv.org/abs/2401.15947)（2024，被引 403）：MoE-LLaVA三阶段解耦训练，解决稀疏LVLM训练崩溃
- **最新** [Kimi-VL Technical Report](https://arxiv.org/abs/2504.07491)（2025，被引 363）：Kimi-VL高效MoE视觉语言模型，激活2.8B参数
- **最新** [MoETok: Sparse Expert Routing for 1D Visual Tokenizers](https://arxiv.org/abs/2610.41992)（2026，被引 0）：MoETok按Content/Detail角色稀疏路由视觉token

## MoE理论分析与综述

系统梳理MoE的算法、系统与应用，分析缩放规律与硬件协同设计，为后续研究提供分类体系与设计指南。

- **起点** [Efficient Large Scale Language Modeling with Mixtures of Experts](https://arxiv.org/abs/2112.10684)（2021，被引 262）：系统实证对比MoE与稠密模型缩放，MoE约省4倍算力
- **里程碑** [A Survey on Mixture of Experts in Large Language Models](https://arxiv.org/abs/2407.06204)（2024，被引 436）：提出MoE分类体系，梳理算法、系统与开源实现
- **最新** [A Comprehensive Survey of Mixture-of-Experts: Algorithms, Theory, and Applications](https://arxiv.org/abs/2503.07137)（2025，被引 142）：全面综述门控、路由、训练策略与多领域应用
- **最新** [Insights into DeepSeek-V3: Scaling Challenges and Reflections on Hardware for AI Architectures](https://arxiv.org/abs/2505.09343)（2025，被引 113）：分析DeepSeek-V3硬件感知协同设计，讨论AI硬件方向

## 稠密基础模型与缩放

MoE的兴起离不开稠密Transformer与缩放定律的支撑。Transformer奠定架构基础，GPT-3与缩放定律揭示规模收益，Chinchilla给出计算最优配比，LLaMA与Llama 3等开源模型推动大模型普及，为MoE提供对照与基础。

- **起点** [Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）：提出Transformer架构，成为所有大模型的基础
- **里程碑** [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)（2020，被引 66,022）：GPT-3 175B展示少样本学习能力
- **里程碑** [Scaling Laws for Neural Language Models](https://arxiv.org/abs/2001.08361)（2020，被引 9,542）：发现语言模型损失随规模幂律下降
- **改进** [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)（2022，被引 3,996）：Chinchilla给出计算最优的模型与数据等比例扩展
- **改进** [LLaMA: Open and Efficient Foundation Language Models](https://arxiv.org/abs/2302.13971)（2023，被引 22,487）：LLaMA开源基础模型，13B超GPT-3
- **最新** [The Llama 3 Herd of Models](https://arxiv.org/abs/2407.21783)（2024，被引 20,607）：Llama 3 405B稠密模型媲美GPT-4并开源
- **最新** [Qwen2.5 Technical Report](https://arxiv.org/abs/2412.15115)（2024，被引 5,760）：Qwen2.5 72B性能媲美5倍大的Llama-3-405B

## 高效训练与推理系统

大模型训练受显存与通信限制，Megatron-LM层内并行、GPipe流水线并行、ZeRO显存优化与DeepSpeed共同支撑超大规模训练；推理侧投机解码与PagedAttention降低延迟，为MoE系统提供底层支撑。

- **起点** [Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism](https://arxiv.org/abs/1909.08053)（2019，被引 3,361）：提出层内模型并行，在512 GPU训练8.3B模型
- **改进** [GPipe: Efficient Training of Giant Neural Networks using Pipeline Parallelism](https://www.semanticscholar.org/paper/d79a26226393f687ddbc375e32055b40b8ad8d38)（2018，被引 2,366）：GPipe流水线并行，实现近线性加速
- **改进** [ZeRO: Memory optimizations Toward Training Trillion Parameter Models](https://arxiv.org/abs/1910.02054)（2019，被引 2,228）：ZeRO消除显存冗余，线性扩展模型规模
- **改进** [DeepSpeed: System Optimizations Enable Training Deep Learning Models with Over 100 Billion Parameters](https://www.semanticscholar.org/paper/725264948d7b6946259af5b8d966e996b9570f99)（2020，被引 2,349）：DeepSpeed与ZeRO，3-5倍吞吐训练超1000亿参数
- **改进** [Efficient Large-Scale Language Model Training on GPU Clusters Using Megatron-LM](https://arxiv.org/abs/2104.04473)（2021，被引 1,467）：组合三种并行与交错流水线，训练1万亿参数模型
- **改进** [Fast Inference from Transformers via Speculative Decoding](https://arxiv.org/abs/2211.17192)（2022，被引 2,311）：投机解码用小模型草稿加速大模型推理2-3倍
- **改进** [Training Deep Nets with Sublinear Memory Cost](https://arxiv.org/abs/1604.06174)（2016，被引 1,673）：亚线性显存训练算法，1000层ResNet显存从48G降到7G

## 参数高效微调与适配

全参数微调成本高昂，Adapter、Prefix-Tuning、Prompt Tuning与LoRA逐步降低可训练参数，使大模型多任务适配更高效，这些技术也常与MoE模型结合用于下游任务。

- **起点** [Parameter-Efficient Transfer Learning for NLP](https://arxiv.org/abs/1902.00751)（2019，被引 7,824）：Adapter模块仅训练3.6%参数达到近全量微调性能
- **改进** [Prefix-Tuning: Optimizing Continuous Prompts for Generation](https://arxiv.org/abs/2101.00190)（2021，被引 6,675）：Prefix-Tuning仅优化0.1%连续前缀参数
- **改进** [The Power of Scale for Parameter-Efficient Prompt Tuning](https://arxiv.org/abs/2104.08691)（2021，被引 6,319）：Prompt Tuning软提示随规模逼近全量微调
- **里程碑** [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)（2021，被引 25,273）：LoRA低秩分解，可训练参数减少1万倍且无推理延迟

## 预训练目标与架构基础

BERT双向掩码预训练、GPT-2无监督多任务、T5统一文本到文本框架与RoBERTa稳健优化，共同奠定大语言模型的预训练范式与架构组件，为MoE模型提供基础模块。

- **起点** [BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)（2019，被引 124,949）：BERT双向Transformer预训练，刷新11项NLP任务
- **改进** [Language Models are Unsupervised Multitask Learners](https://www.semanticscholar.org/paper/9405cc0d6169988371b2755e573cc28650d14dfe)（2019，被引 31,274）：GPT-2证明语言模型可零样本多任务学习
- **改进** [Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer](https://arxiv.org/abs/1910.10683)（2019，被引 28,232）：T5统一文本到文本框架，系统对比预训练目标
- **改进** [RoBERTa: A Robustly Optimized BERT Pretraining Approach](https://arxiv.org/abs/1907.11692)（2019，被引 32,404）：RoBERTa发现BERT欠训练，调整后达SOTA
- **变体** [ALBERT: A Lite BERT for Self-supervised Learning of Language Representations](https://arxiv.org/abs/1909.11942)（2019，被引 7,893）：ALBERT参数共享与嵌入分解，大幅减少参数量
- **基础** [Layer Normalization](https://arxiv.org/abs/1607.06450)（2016，被引 13,730）：Layer Normalization对单样本归一化，易用于RNN
- **基础** [Gaussian Error Linear Units (GELUs)](https://arxiv.org/abs/1606.08415)（2016，被引 7,746）：GELU激活函数按输入值加权，优于ReLU
- **改进** [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864)（2021，被引 7,061）：RoPE旋转位置编码显式引入相对位置依赖
- **基础** [Identity Mappings in Deep Residual Networks](https://arxiv.org/abs/1603.05027)（2016，被引 11,678）：pre-activation残差单元使信号直通，训练1001层网络

## 缩放规律与涌现能力

缩放定律揭示模型性能随规模幂律提升，Chinchilla修正数据配比，涌现能力分析表明大模型出现小模型无法预测的能力，数据规模效应在视觉领域也得到验证，这些研究为MoE的规模扩展提供理论依据。

- **起点** [Scaling Laws for Neural Language Models](https://arxiv.org/abs/2001.08361)（2020，被引 9,542）：发现语言模型损失随规模、数据、算力幂律下降
- **改进** [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)（2022，被引 3,996）：Chinchilla修正模型与数据应等比例扩展
- **改进** [Emergent Abilities of Large Language Models](https://arxiv.org/abs/2206.07682)（2022，被引 3,966）：系统刻画涌现能力，小模型无法外推预测
- **改进** [Revisiting Unreasonable Effectiveness of Data in Deep Learning Era](https://arxiv.org/abs/1707.02968)（2017，被引 2,827）：JFT-300M验证视觉任务性能随数据量对数增长
- **里程碑** [PaLM: Scaling Language Modeling with Pathways](https://arxiv.org/abs/2204.02311)（2022，被引 8,578）：PaLM 540B验证few-shot与推理随规模涌现
- **改进** [OPT: Open Pre-trained Transformer Language Models](https://arxiv.org/abs/2205.01068)（2022，被引 5,147）：OPT开放175B模型媲美GPT-3，碳足迹仅1/7
- **最新** [Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone](https://arxiv.org/abs/2404.14219)（2024，被引 2,633）：phi-3 3.8B用高质量数据训练，MMLU达69%可手机部署

## 评测基准与解码策略

MMLU与GSM8K等基准衡量模型知识与推理能力，MMStar揭示多模态基准的视觉依赖与泄漏问题，Nucleus Sampling改进解码质量，这些评测与解码方法为MoE模型的能力评估提供工具。

- **起点** [Measuring Massive Multitask Language Understanding](https://arxiv.org/abs/2009.03300)（2020，被引 10,379）：MMLU覆盖57学科，发现GPT-3仅超随机20个百分点
- **改进** [Training Verifiers to Solve Math Word Problems](https://arxiv.org/abs/2110.14168)（2021，被引 11,892）：GSM8K数学应用题基准与验证器提升推理
- **改进** [The Curious Case of Neural Text Degeneration](https://arxiv.org/abs/1904.09751)（2019，被引 4,736）：Nucleus Sampling动态概率核采样兼顾多样与流畅
- **最新** [Are We on the Right Way for Evaluating Large Vision-Language Models?](https://arxiv.org/abs/2403.20330)（2024，被引 1,088）：MMStar揭示多模态基准视觉非必要与数据泄漏问题

## 推荐综述

- [A Survey on Mixture of Experts in Large Language Models](https://arxiv.org/abs/2407.06204)（2024，被引 436）
- [A Comprehensive Survey of Mixture-of-Experts: Algorithms, Theory, and Applications](https://arxiv.org/abs/2503.07137)（2025，被引 142）

## 仍未解决

- MoE路由的专家专业化与负载均衡仍难兼得
- 超大规模MoE训练与推理的通信开销仍高
- MoE在RL后训练中的路由稳定性缺乏通用方案
- MoE模型的可解释性与专家功能分工尚不清晰

<sub>召回 346 篇 → 子图 346 篇 → 选 88 篇成线；花费 $0.0041</sub>