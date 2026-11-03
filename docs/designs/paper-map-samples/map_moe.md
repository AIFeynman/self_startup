# 混合专家 MoE 研究脉络

MoE 主题旨在解决大模型容量扩展与计算成本之间的矛盾：通过稀疏路由让每个 token 只激活部分专家，在保持推理算力可控的同时大幅增加参数量。脉络从 1991 年自适应局部专家混合与 1993 年分层 MoE 的统计学习框架起步，2017 年稀疏门控 MoE 层将其引入深度学习并堆叠至 137B 参数；随后 GShard、Switch Transformer、GLaM 等解决分布式训练、路由简化与负载均衡问题，将 MoE 推进至万亿参数。2024 年后 DeepSeekMoE 的细粒度专家与共享专家、无辅助损失负载均衡、MLA 等推动 MoE 成为主流开源大模型架构，并扩展到多模态、推荐、扩散模型与强化学习等场景。

**前置基础**：[Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）；[Adaptive Mixtures of Local Experts](https://www.semanticscholar.org/paper/c8d90974c3f3b40fa05e322df2905fc16204aa56)（1991，被引 7,382）；[Layer Normalization](https://arxiv.org/abs/1607.06450)（2016，被引 13,730）；[Estimating or Propagating Gradients Through Stochastic Neurons for Conditional Computation](https://arxiv.org/abs/1308.3432)（2013，被引 4,473）；[BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)（2019，被引 124,949）；[Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer](https://arxiv.org/abs/1910.10683)（2019，被引 28,232）

## 稀疏门控与路由演进

从自适应局部专家混合出发，稀疏门控 MoE 层首次在深度网络中实现 top-k 稀疏路由并堆叠至 137B 参数；Switch Transformer 简化为 top-1 路由并改进稳定性；GShard 提供自动分片系统支撑 600B 规模；后续专家选择路由与 Soft MoE 分别从反向选择和全可微分配角度解决负载不均衡与 token 丢弃问题。

- **起点** [Adaptive Mixtures of Local Experts](https://www.semanticscholar.org/paper/c8d90974c3f3b40fa05e322df2905fc16204aa56)（1991，被引 7,382）：奠定门控网络为每个样本选择专家子网络的基本框架
- **改进** [Hierarchical Mixtures of Experts and the EM Algorithm](https://www.semanticscholar.org/paper/f6d8a7fc2e2d53923832f9404376512068ca2a57)（1993，被引 3,885）：将 MoE 扩展为树状分层结构并用 EM 算法训练
- **改进** [Learning Factored Representations in a Deep Mixture of Experts](https://arxiv.org/abs/1312.4314)（2013，被引 507）：堆叠多层门控与专家，指数级增加有效专家数
- **里程碑** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：提出稀疏门控 MoE 层，top-k 路由堆叠至 137B 参数
- **里程碑** [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668)（2020，被引 2,554）：用自动分片系统将稀疏 MoE 扩至 600B 参数
- **里程碑** [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)（2021，被引 5,265）：简化为 top-1 路由并改进训练稳定性，扩展至万亿参数
- **改进** [GLaM: Efficient Scaling of Language Models with Mixture-of-Experts](https://arxiv.org/abs/2112.06905)（2021，被引 1,379）：1.2T 参数 MoE 以更低能耗在 29 个任务上优于 GPT-3
- **变体** [Mixture-of-Experts with Expert Choice Routing](https://arxiv.org/abs/2202.09368)（2022，被引 984）：专家反向选择 token，实现可变路由与负载均衡
- **变体** [From Sparse to Soft Mixtures of Experts](https://arxiv.org/abs/2308.00951)（2023，被引 379）：全可微软分配替代稀疏路由，解决训练不稳定与 token 丢弃
- **里程碑** [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)（2024，被引 1,277）：细粒度专家切分与共享专家隔离，促进专家专业化
- **改进** [Demons in the Detail: On Implementing Load Balancing Loss for Training Specialized Mixture-of-Expert Models](https://arxiv.org/abs/2501.11873)（2025，被引 71）：用 global-batch 负载均衡损失避免抑制专家专业化
- **最新** [DeepSeek-V3 Technical Report](https://www.semanticscholar.org/paper/5b6fdb2aea424d02c141da81d62b04d739d62b96)（2024，被引 4,377）：无辅助损失负载均衡的 MoE 与 FP8 训练，性能比肩闭源

## MoE 大模型规模化

在稀疏路由基础上，GShard 与 Switch Transformer 解决分布式训练与稳定性问题，将 MoE 推向万亿参数；GLaM 验证稀疏激活在能耗与推理 FLOPs 上的优势；DeepSeekMoE 通过细粒度专家与共享专家提升专家专业化；DeepSeek-V2/V3 结合 MLA 与无辅助损失负载均衡，以 236B/671B 总参、21B/37B 激活实现高效训练推理；Mixtral、Qwen3、gpt-oss 等进一步将 MoE 推广为主流开源架构。

- **起点** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：首次在深度网络中实现稀疏门控 MoE 并堆叠至 137B
- **里程碑** [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668)（2020，被引 2,554）：自动分片系统支撑 600B 参数 MoE 多语言翻译
- **相关** [Measuring Massive Multitask Language Understanding](https://arxiv.org/abs/2009.03300)（2020，被引 10,379）：构建覆盖57个学科的多任务选择题基准MMLU，发现最大GPT-3仅比随机高约20个百分点，各任务均远未达专家水平。
- **相关** [The Pile: An 800GB Dataset of Diverse Text for Language Modeling](https://arxiv.org/abs/2101.00027)（2020，被引 3,165）：构建 825GiB、22 个子集的多样化英文预训练语料 The Pile，实验表明在其上训练的模型全面优于 Raw CC 与 CC-100 并提升下游表现。
- **里程碑** [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)（2021，被引 5,265）：top-1 路由与 bfloat16 训练，同算力预训练提速 7 倍
- **里程碑** [GLaM: Efficient Scaling of Language Models with Mixture-of-Experts](https://arxiv.org/abs/2112.06905)（2021，被引 1,379）：1.2T 参数仅用 GPT-3 约 1/3 训练能耗
- **改进** [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)（2024，被引 1,277）：细粒度专家与共享专家隔离，16B 仅用 40% 算力比肩 LLaMA2 7B
- **里程碑** [Mixtral of Experts](https://arxiv.org/abs/2401.04088)（2024，被引 2,263）：47B 总参 13B 激活，性能匹配 Llama 2 70B 与 GPT-3.5
- **改进** [DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model](https://arxiv.org/abs/2405.04434)（2024，被引 1,589）：MLA 压缩 KV cache，训练省 42.5%、吞吐提升 5.76 倍
- **里程碑** [DeepSeek-V3 Technical Report](https://www.semanticscholar.org/paper/5b6fdb2aea424d02c141da81d62b04d739d62b96)（2024，被引 4,377）：无辅助损失负载均衡与 FP8 训练，性能比肩闭源领先模型
- **最新** [Qwen3 Technical Report](https://arxiv.org/abs/2505.09388)（2025，被引 9,881）：统一思考/非思考模式并引入 thinking budget，MoE 与稠密并行
- **最新** [gpt-oss-120b&gpt-oss-20b Model Card](https://arxiv.org/abs/2508.10925)（2025，被引 1,613）：开放权重 MoE 推理模型，经大规模蒸馏与 RL 训练

## MoE 训练稳定性与均衡

MoE 训练面临路由不稳定、负载不均衡与专家欠训练等核心难题。ST-MoE 系统研究稳定性并给出 router z-loss 等设计指南；专家选择路由从反向选择实现负载均衡；DeepSeekMoE 用细粒度专家与共享专家缓解知识冗余；global-batch 负载均衡损失避免 micro-batch 强制均匀路由抑制专业化；R3 回放推理路由分布解决 MoE 强化学习中的路由不一致崩溃。

- **起点** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：提出稀疏门控 MoE，同时暴露负载不均衡问题
- **改进** [ST-MoE: Designing Stable and Transferable Sparse Expert Models](https://arxiv.org/abs/2202.08906)（2022，被引 506）：router z-loss 与专家 dropout 系统提升训练稳定性
- **变体** [Mixture-of-Experts with Expert Choice Routing](https://arxiv.org/abs/2202.09368)（2022，被引 984）：专家反向选择 token，实现可变路由与负载均衡
- **改进** [DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models](https://arxiv.org/abs/2401.06066)（2024，被引 1,277）：细粒度专家与共享专家隔离，缓解专家知识重叠冗余
- **改进** [Demons in the Detail: On Implementing Load Balancing Loss for Training Specialized Mixture-of-Expert Models](https://arxiv.org/abs/2501.11873)（2025，被引 71）：global-batch 负载均衡损失促进专家专业化
- **里程碑** [DeepSeek-V3 Technical Report](https://www.semanticscholar.org/paper/5b6fdb2aea424d02c141da81d62b04d739d62b96)（2024，被引 4,377）：无辅助损失负载均衡策略，避免均衡损失损害性能
- **最新** [Stabilizing MoE Reinforcement Learning by Aligning Training and Inference Routers](https://arxiv.org/abs/2510.11370)（2025，被引 86）：R3 回放推理路由分布，稳定 MoE 强化学习训练

## MoE 系统与高效推理

MoE 的稀疏计算带来显存、通信与推理效率挑战。GShard 提供自动分片与 XLA 扩展；DeepSpeed-MoE 给出端到端训练推理方案与压缩技术；MegaBlocks 将 MoE 计算重构为块稀疏操作避免丢 token；PagedAttention/vLLM 优化 KV cache 内存管理；DeepSeek-V3 进一步用 MLA、FP8 与多平面网络实现软硬件协同设计。

- **起点** [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668)（2020，被引 2,554）：GShard 注解 API 与 XLA 扩展实现自动分片
- **改进** [DeepSpeed-MoE: Advancing Mixture-of-Experts Inference and Training to Power Next-Generation AI Scale](https://arxiv.org/abs/2201.05596)（2022，被引 703）：端到端 MoE 训练推理方案，推理延迟降 7.3 倍
- **改进** [MegaBlocks: Efficient Sparse Training with Mixture-of-Experts](https://arxiv.org/abs/2211.15841)（2022，被引 302）：块稀疏 GPU 内核避免丢 token，训练较 Megatron 提速 2.4 倍
- **里程碑** [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)（2023，被引 9,724）：PagedAttention 实现 KV cache 近零浪费，吞吐提升 2-4 倍
- **改进** [DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model](https://arxiv.org/abs/2405.04434)（2024，被引 1,589）：MLA 压缩 KV cache 93.3%，推理吞吐提升 5.76 倍
- **里程碑** [DeepSeek-V3 Technical Report](https://www.semanticscholar.org/paper/5b6fdb2aea424d02c141da81d62b04d739d62b96)（2024，被引 4,377）：FP8 混合精度与无辅助损失 MoE 实现高效大规模训练
- **最新** [Insights into DeepSeek-V3: Scaling Challenges and Reflections on Hardware for AI Architectures](https://arxiv.org/abs/2505.09343)（2025，被引 113）：软硬件协同设计分析，提出多平面网络等下一代方向

## MoE 多模态与跨领域扩展

MoE 从语言建模扩展到视觉、多模态、推荐与扩散模型。V-MoE 将稀疏 MoE 引入视觉 Transformer 并实现按图像自适应计算；LIMoE 用对比损失训练多模态稀疏 MoE 并均衡专家；MoE-LLaVA 用三阶段解耦训练解决 LLM 转稀疏 LVLM 崩溃；DeepSeek-VL2 与 Kimi-VL 结合 MoE 与动态切图/原生分辨率编码器；OneRec 将稀疏 MoE 用于生成式推荐；LLaDA-MoE 验证 MoE 在扩散语言模型中的有效性。

- **起点** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：稀疏门控 MoE 层为跨领域扩展提供基础框架
- **改进** [Scaling Vision with Sparse Mixture of Experts](https://arxiv.org/abs/2106.05974)（2021，被引 1,267）：V-MoE 将稀疏 MoE 引入视觉，推理算力减半
- **变体** [Multimodal Contrastive Learning with LIMoE: the Language-Image Mixture of Experts](https://arxiv.org/abs/2206.02770)（2022，被引 372）：LIMoE 用对比损失训练多模态稀疏 MoE 并均衡专家
- **改进** [MoE-LLaVA: Mixture of Experts for Large Vision-Language Models](https://arxiv.org/abs/2401.15947)（2024，被引 403）：三阶段解耦训练解决 LLM 转稀疏 LVLM 崩溃
- **改进** [DeepSeek-VL2: Mixture-of-Experts Vision-Language Models for Advanced Multimodal Understanding](https://arxiv.org/abs/2412.10302)（2024，被引 730）：动态切图编码与 MLA 压缩 KV cache 提升多模态效率
- **最新** [Kimi-VL Technical Report](https://arxiv.org/abs/2504.07491)（2025，被引 363）：MoE 解码器配原生分辨率编码器，激活 2.8B 媲美旗舰
- **变体** [OneRec: Unifying Retrieve and Rank with Generative Recommender and Iterative Preference Alignment](https://arxiv.org/abs/2502.18965)（2025，被引 373）：稀疏 MoE 用于端到端生成式推荐，超越级联系统
- **最新** [LLaDA-MoE: A Sparse MoE Diffusion Language Model](https://arxiv.org/abs/2509.24389)（2025，被引 60）：从零训练稀疏 MoE 扩散语言模型，7B 容量仅激活 1.4B

## MoE 缩放规律与稀疏度设计

MoE 的参数量与每 token 激活 FLOPs 如何权衡是核心设计问题。Scaling Laws 给出稠密模型损失与规模的幂律关系；Chinchilla 揭示模型与 token 应等比例扩展；Switch Transformer 与 GLaM 实证稀疏激活的算力效率；后续工作系统研究 MoE 稀疏度对预训练与下游的影响，发现给定参数或算力约束下存在最优稀疏度，并探索条件记忆等新稀疏轴。

- **起点** [Scaling Laws for Neural Language Models](https://arxiv.org/abs/2001.08361)（2020，被引 9,542）：给出损失随模型、数据与算力幂律下降的定量规律
- **改进** [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)（2022，被引 3,996）：揭示计算最优时模型与 token 应等比例扩展
- **里程碑** [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)（2021，被引 5,265）：实证同算力下稀疏 MoE 预训练提速 7 倍
- **改进** [GLaM: Efficient Scaling of Language Models with Mixture-of-Experts](https://arxiv.org/abs/2112.06905)（2021，被引 1,379）：1.2T 参数仅用 GPT-3 约 1/3 训练能耗与一半推理 FLOPs
- **最新** [Parameters vs FLOPs: Scaling Laws for Optimal Sparsity for Mixture-of-Experts Language Models](https://arxiv.org/abs/2501.12370)（2025，被引 61）：系统研究 MoE 稀疏度缩放规律，发现存在最优稀疏度
- **最新** [Conditional Memory via Scalable Lookup: A New Axis of Sparsity for Large Language Models](https://arxiv.org/abs/2601.07372)（2026，被引 96）：提出条件记忆作为新稀疏轴，27B 规模超越等参等 FLOPs MoE

## MoE 基础架构与预训练支撑

MoE 的高效训练依赖底层架构与预训练技术。Transformer 与 BERT 提供基础架构；LayerNorm、GELU、RoPE 等组件提升训练稳定性与位置建模；Megatron-LM 与 GPipe 解决模型并行与流水线并行；知识蒸馏将大模型知识压缩到小模型；稀疏注意力与 FlashAttention 降低长序列计算开销；GPT-3、PaLM、LLaMA、Llama 3、Qwen2.5 等稠密模型为 MoE 提供缩放经验与对照基线。

- **改进** [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)（2015，被引 27,519）：知识蒸馏将大模型知识压缩到单模型
- **改进** [Layer Normalization](https://arxiv.org/abs/1607.06450)（2016，被引 13,730）：LayerNorm 稳定深层网络训练
- **改进** [Gaussian Error Linear Units (GELUs)](https://arxiv.org/abs/1606.08415)（2016，被引 7,746）：GELU 平滑激活提升模型性能
- **起点** [Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）：Transformer 架构成为 MoE 模型的骨干网络
- **改进** [GPipe: Efficient Training of Giant Neural Networks using Pipeline Parallelism](https://www.semanticscholar.org/paper/d79a26226393f687ddbc375e32055b40b8ad8d38)（2018，被引 2,366）：GPipe 流水线并行实现近线性加速
- **里程碑** [Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism](https://arxiv.org/abs/1909.08053)（2019，被引 3,361）：Megatron-LM 层内模型并行支撑十亿级参数训练
- **改进** [Generating Long Sequences with Sparse Transformers](https://arxiv.org/abs/1904.10509)（2019，被引 2,776）：稀疏注意力将复杂度降至 O(n√n)，支持超长序列
- **相关** [ALBERT: A Lite BERT for Self-supervised Learning of Language Representations](https://arxiv.org/abs/1909.11942)（2019，被引 7,893）：提出ALBERT，用嵌入分解与跨层参数共享降低BERT参数量，并以句序预测替代NSP，在GLUE/RACE/SQuAD刷新SOTA。
- **里程碑** [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)（2020，被引 66,022）：GPT-3 揭示缩放收益与少样本泛化能力
- **改进** [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864)（2021，被引 7,061）：RoPE 旋转位置编码支持长序列与相对位置依赖
- **里程碑** [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)（2022，被引 5,766）：FlashAttention IO 感知精确注意力，训练提速 2-4 倍
- **改进** [PaLM: Scaling Language Modeling with Pathways](https://arxiv.org/abs/2204.02311)（2022，被引 8,578）：PaLM 540B 验证 few-shot 与多步推理随规模涌现
- **改进** [LLaMA: Open and Efficient Foundation Language Models](https://arxiv.org/abs/2302.13971)（2023，被引 22,487）：LLaMA 开源高效基础模型，13B 多数基准超 GPT-3
- **最新** [The Llama 3 Herd of Models](https://arxiv.org/abs/2407.21783)（2024，被引 20,607）：Llama 3 405B 稠密模型质量媲美 GPT-4
- **最新** [Qwen2.5 Technical Report](https://arxiv.org/abs/2412.15115)（2024，被引 5,760）：Qwen2.5 18T token 预训练与多阶段 RL，含 MoE 变体
- **相关** [Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone](https://arxiv.org/abs/2404.14219)（2024，被引 2,633）：发布phi-3系列技术报告，3.8B模型用3.3T过滤网页与合成数据训练，MMLU达69%，可手机部署并扩展MoE与视觉版本。

## 推荐综述

- [A Survey on Mixture of Experts in Large Language Models](https://arxiv.org/abs/2407.06204)（2024，被引 436）
- [A Comprehensive Survey of Mixture-of-Experts: Algorithms, Theory, and Applications](https://arxiv.org/abs/2503.07137)（2025，被引 142）

## 仍未解决

- MoE 路由的负载均衡与专家专业化仍难兼得
- 超大规模 MoE 训练与推理的通信开销仍高
- MoE 在强化学习与多模态中的路由稳定性不足
- 最优稀疏度与专家粒度的理论指导仍缺乏

<sub>召回 246 篇 → 子图 246 篇 → 选 88 篇成线；花费 $0.0045</sub>