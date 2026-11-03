# 检索增强生成 RAG 研究脉络

RAG 旨在解决大模型知识固化、幻觉与不可溯源问题，通过外部检索增强生成。脉络从早期开放域QA的检索-阅读器（DrQA、DPR）与端到端联合训练（REALM、RAG）起步，随后向生成式融合（FiD、RETRO、Atlas）与黑盒/上下文增强（REPLUG、In-Context RALM）扩展；2023年后转向自适应与多步检索（Self-RAG、FLARE、IRCoT）、图结构增强（GraphRAG、PathRAG）以及多模态与多智能体系统，同时评测与可信性研究同步跟进。

**前置基础**：[BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)（2019，被引 124,949）；[Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）；[Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)（2020，被引 66,022）；[GloVe: Global Vectors for Word Representation](https://www.semanticscholar.org/paper/f37e1b62a767a307c046404ca96bc140b3e68cb5)（2014，被引 35,863）；[The Probabilistic Relevance Framework: BM25 and Beyond](https://www.semanticscholar.org/paper/47ced790a563344efae66588b5fb7fe6cca29ed3)（2009，被引 6,906）；[Billion-Scale Similarity Search with GPUs](https://arxiv.org/abs/1702.08734)（2017，被引 6,486）

## 检索-阅读器流水线

早期开放域QA将文档检索与机器阅读理解分离，用稀疏检索加神经阅读器；DPR 用稠密双编码器显著提升召回，Sentence-BERT 与 SimCSE 改进句向量，ColBERT 延迟交互兼顾效率，奠定后续 RAG 的检索基础。

- **相关** [MS MARCO: A Human Generated MAchine Reading COmprehension Dataset](https://arxiv.org/abs/1611.09268)（2016，被引 4,002）：构建MS MARCO大规模机器阅读理解数据集，问题取自真实匿名用户查询、答案人工生成，首批发布10万条查询推动阅读理解与问答研究。
- **起点** [Reading Wikipedia to Answer Open-Domain Questions](https://arxiv.org/abs/1704.00051)（2017，被引 2,328）：首次组合 TF-IDF 检索与 RNN 阅读器解决开放域QA
- **相关** [A Broad-Coverage Challenge Corpus for Sentence Understanding through Inference](https://arxiv.org/abs/1704.05426)（2017，被引 5,378）：构建43.3万条、覆盖十种文体的MultiNLI语料，用于句子理解与跨领域NLI评测，实验显示其难度显著高于SNLI。
- **改进** [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084)（2019，被引 22,085）：孪生BERT句向量使语义检索从65小时降至5秒
- **里程碑** [Dense Passage Retrieval for Open-Domain Question Answering](https://arxiv.org/abs/2004.04906)（2020，被引 7,708）：用稠密双编码器替代稀疏检索，top-20召回提升9-19%
- **变体** [ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT](https://arxiv.org/abs/2004.12832)（2020，被引 2,804）：延迟交互兼顾BERT排序效果与离线检索效率
- **改进** [SimCSE: Simple Contrastive Learning of Sentence Embeddings](https://arxiv.org/abs/2104.08821)（2021，被引 4,952）：对比学习缓解句向量各向异性，提升检索质量
- **相关** [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864)（2021，被引 7,061）：提出RoPE用旋转矩阵编码绝对位置并注入显式相对位置依赖，支持序列长度灵活与远程衰减，长文本分类上稳定优于替代方案。

## 端到端联合训练RAG

将检索器与生成器端到端联合训练，使检索信号直接来自生成任务；REALM 无监督预训练检索器，RAG 统一参数与非参数记忆，Atlas 进一步验证少样本下的有效性，RETRO 用分块交叉注意力扩展到万亿token。

- **相关** [Think you have Solved Question Answering? Try ARC, the AI2 Reasoning Challenge](https://arxiv.org/abs/1803.05457)（2018，被引 6,103）：提出 ARC 推理挑战集，含 7787 道小学科学题及 14M 句语料，Challenge Set 上 SQuAD/SNLI 强基线均无法显著超过随机，凸显任务
- **相关** [Natural Questions: A Benchmark for Question Answering Research](https://www.semanticscholar.org/paper/17dbd7b72029181327732e4d11b52a08ed4630d0)（2019，被引 5,469）：发布 Natural Questions，含 30 万真实 Google 搜索查询及维基长/短答案标注，提出稳健评测指标并给出人类上限与基线结果。
- **起点** [REALM: Retrieval-Augmented Language Model Pre-Training](https://arxiv.org/abs/2002.08909)（2020，被引 3,602）：用掩码语言建模信号无监督预训练潜在检索器
- **里程碑** [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)（2020，被引 20,501）：统一参数与非参数记忆，两种生成形式达SOTA
- **变体** [Improving language models by retrieving from trillions of tokens](https://arxiv.org/abs/2112.04426)（2021，被引 2,016）：用2万亿token检索库，参数少25倍媲美GPT-3
- **改进** [Few-shot Learning with Retrieval Augmented Language Models](https://arxiv.org/abs/2208.03299)（2022，被引 1,471）：检索增强预训练，64例即超越540B模型
- **相关** [LaMDA: Language Models for Dialog Applications](https://arxiv.org/abs/2201.08239)（2022，被引 1,944）：发布137B对话模型LaMDA，用标注微调与外部知识检索提升安全与事实依据，分类器过滤候选回复改善安全性。
- **相关** [PaLM: Scaling Language Modeling with Pathways](https://arxiv.org/abs/2204.02311)（2022，被引 8,578）：发布540B稠密Transformer模型PaLM，用Pathways跨6144 TPU v4训练，验证few-shot与多步推理随规模持续提升并现涌现。

## 生成式融合与上下文增强

探索如何将检索段落有效融入生成：FiD 分别编码多段落再融合，REPLUG 与 In-Context RALM 面向黑盒模型直接前置文档，降低部署门槛；同时长上下文模型（Lost in the Middle）揭示位置偏差，推动上下文组织研究。

- **相关** [TriviaQA: A Large Scale Distantly Supervised Challenge Dataset for Reading Comprehension](https://arxiv.org/abs/1705.03551)（2017，被引 4,646）：发布含 65 万问答-证据三元组的 TriviaQA 阅读理解数据集，问题更复杂需跨句推理，基线远低于人类 80%。
- **起点** [Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering](https://arxiv.org/abs/2007.01282)（2020，被引 2,209）：多段落分别编码再解码聚合，性能随段落数提升
- **相关** [Scaling Instruction-Finetuned Language Models](https://arxiv.org/abs/2210.11416)（2022，被引 4,562）：系统研究指令微调在任务数、模型规模与 CoT 数据上的缩放，Flan-PaLM 540B 在 1.8K 任务上平均提升 9.4%，MMLU 达 75.2%。
- **变体** [REPLUG: Retrieval-Augmented Black-Box Language Models](https://arxiv.org/abs/2301.12652)（2023，被引 1,167）：冻结黑盒LM前置文档并用LM监督检索器
- **改进** [In-Context Retrieval-Augmented Language Models](https://arxiv.org/abs/2302.00083)（2023，被引 1,190）：不改架构直接前置检索文档，现成检索器即增益
- **改进** [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)（2023，被引 5,819）：揭示长上下文U形位置偏差，指导检索文档排序

## 自适应与多步检索

针对固定一次性检索的不足，让模型按需、多步、迭代地检索：FLARE 在低置信处触发检索，IRCoT 将检索与思维链交替，Self-RAG 用反思token自我评判，PopQA 揭示长尾知识记忆差，推动自适应检索策略。

- **改进** [Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions](https://arxiv.org/abs/2212.10509)（2022，被引 1,486）：检索与思维链步骤交替，多步QA提升最多15点
- **改进** [When Not to Trust Language Models: Investigating Effectiveness of Parametric and Non-Parametric Memories](https://arxiv.org/abs/2212.10511)（2022，被引 1,626）：揭示长尾知识记忆差，提出仅在需要时检索
- **相关** [Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155)（2022，被引 25,663）：提出InstructGPT用人类示范SFT加排序RLHF微调GPT-3，1.3B模型输出比175B GPT-3更受偏好且更真实。
- **起点** [Active Retrieval Augmented Generation](https://arxiv.org/abs/2305.06983)（2023，被引 953）：用下句预测作查询，低置信token处主动重新检索
- **里程碑** [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)（2023，被引 3,017）：反思token实现按需检索与自我评判，7B超越ChatGPT

## 图结构与知识组织

用知识图谱或实体图组织检索单元，解决扁平文本RAG难以回答全局问题与忽略chunk间关系的问题；GraphRAG 构建社区摘要，PathRAG 用关系路径剪枝，KG²RAG 用KG扩展组织chunk，HippoRAG 2 模拟关联记忆。

- **起点** [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)（2024，被引 2,495）：用实体知识图谱与社区摘要回答全局问题
- **改进** [Knowledge Graph-Guided Retrieval Augmented Generation](https://arxiv.org/abs/2502.06864)（2025，被引 165）：用KG事实关系扩展与组织chunk，提升连贯性
- **改进** [PathRAG: Pruning Graph-based Retrieval Augmented Generation with Relational Paths](https://arxiv.org/abs/2502.14902)（2025，被引 105）：检索关键关系路径并流式剪枝去冗余
- **变体** [From RAG to Memory: Non-Parametric Continual Learning for Large Language Models](https://arxiv.org/abs/2502.14802)（2025，被引 286）：用Personalized PageRank模拟关联记忆，超越标准RAG

## 多模态与多智能体RAG

将RAG扩展到多模态与复杂异构数据场景，用多智能体分解查询、并行多源检索并融合答案，代表RAG从单模态单轮向跨模态多源协同演进。

- **相关** [Learning Transferable Visual Models From Natural Language Supervision](https://arxiv.org/abs/2103.00020)（2021，被引 59,328）：用4亿图文对做对比预训练得到CLIP，以自然语言指代视觉概念实现零样本迁移，ImageNet零样本精度匹配原ResNet-50。
- **最新** [HM-RAG: Hierarchical Multi-Agent Multimodal Retrieval Augmented Generation](https://arxiv.org/abs/2504.12330)（2025，被引 69）：三层级多智能体多模态RAG，零样本SOTA提升12.95%

## 评测与可信性

随着RAG系统增多，评测从通用QA基准转向RAG专用能力（噪声鲁棒、拒答、信息整合）与无参考自动评估，并关注幻觉、安全与公平等可信性维度；MMLU、GLUE 等通用基准为能力评估提供基础。

- **相关** [ROUGE: A Package for Automatic Evaluation of Summaries](https://www.semanticscholar.org/paper/60b05f32c32519a809f21642ef1eb3eaf3848008)（2004，被引 22,753）：提出ROUGE系列四种基于n-gram与最长公共子序列的摘要自动评测指标，成为文本摘要评测的标准工具。
- **相关** [GLUE: A Multi-Task Benchmark and Analysis Platform for Natural Language Understanding](https://arxiv.org/abs/1804.07461)（2018，被引 9,232）：提出含9项NLU任务、诊断集与在线排行榜的GLUE基准，评测显示当时最优模型绝对分数仍偏低，推动统一NLU研究。
- **相关** [DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter](https://arxiv.org/abs/1910.01108)（2019，被引 10,948）：提出DistilBERT，在预训练阶段用语言建模、蒸馏与余弦距离三重损失蒸馏，参数减40%保留97%能力且推理快60%。
- **相关** [Measuring Massive Multitask Language Understanding](https://arxiv.org/abs/2009.03300)（2020，被引 10,379）：构建覆盖57个学科的多任务选择题基准MMLU，发现最大GPT-3仅比随机高约20个百分点，各任务均远未达专家水平。
- **起点** [TruthfulQA: Measuring How Models Mimic Human Falsehoods](https://arxiv.org/abs/2109.07958)（2021，被引 4,272）：揭示模型模仿错误信念，真实性评测基准
- **里程碑** [Benchmarking Large Language Models in Retrieval-Augmented Generation](https://arxiv.org/abs/2309.01431)（2023，被引 730）：构建RAG专用基准RGB，暴露拒答与整合短板
- **改进** [RAGAs: Automated Evaluation of Retrieval Augmented Generation](https://arxiv.org/abs/2309.15217)（2023，被引 1,297）：无参考自动评估RAG忠实度与相关性
- **改进** [RAG vs. GraphRAG: A Systematic Evaluation and Key Insights](https://arxiv.org/abs/2502.11371)（2025，被引 118）：统一协议系统比较RAG与GraphRAG并提融合策略

## 其它重要工作



- **相关** [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)（2017，被引 6,166）：提出稀疏门控 MoE 层，用可训练门控为每个样本稀疏选择专家，在 LSTM 间卷积式堆叠至 137B 参数，语言建模与翻译上以更低算力超越当时 SOTA。
- **相关** [On the Opportunities and Risks of Foundation Models](https://arxiv.org/abs/2108.07258)（2021，被引 7,734）：系统论述基础模型的机遇与风险，提出同质化与涌现能力概念，呼吁跨学科研究理解其能力边界与社会影响。
- **相关** [Scaling Up Visual and Vision-Language Representation Learning With Noisy Text Supervision](https://arxiv.org/abs/2102.05918)（2021，被引 6,206）：提出ALIGN，用超十亿噪声图文alt-text对训练双编码器对比对齐，规模弥补噪声，零样本分类与图文检索达当时最优。
- **相关** [Improved Baselines with Visual Instruction Tuning](https://arxiv.org/abs/2310.03744)（2023，被引 6,153）：在 LLaVA 框架下系统研究 LMM 设计选择，改用 CLIP-ViT-L-336px+MLP 连接器并加入学术 VQA 数据，13B 模型仅用 1.2M 数
- **相关** [MiniGPT-4: Enhancing Vision-Language Understanding with Advanced Large Language Models](https://arxiv.org/abs/2304.10592)（2023，被引 3,437）：用单投影层将冻结视觉编码器与冻结 Vicuna 对齐，并用详细描述数据二阶段微调，复现出图像描述、手绘建站等 GPT-4 式多模态能力。

## 推荐综述

- [Retrieval-Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2312.10997)（2023，被引 4,421）
- [A Survey on RAG Meeting LLMs: Towards Retrieval-Augmented Large Language Models](https://arxiv.org/abs/2405.06211)（2024，被引 1,246）
- [Retrieval-Augmented Generation for AI-Generated Content: A Survey](https://arxiv.org/abs/2402.19473)（2024，被引 784）
- [Retrieval-Augmented Generation: A Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers](https://arxiv.org/abs/2506.00054)（2025，被引 76）
- [Towards Trustworthy Retrieval Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2502.06872)（2025，被引 70）
- [Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG](https://arxiv.org/abs/2501.09136)（2025，被引 470）
- [A Survey of Graph Retrieval-Augmented Generation for Customized Large Language Models](https://arxiv.org/abs/2501.13958)（2025，被引 169）

## 仍未解决

- 检索质量与生成忠实度的联合优化仍不充分
- 长尾与多跳场景下自适应检索策略待完善
- RAG系统对噪声与对抗输入的鲁棒性不足
- 多模态与多源检索结果冲突消解缺乏统一方法

<sub>召回 933 篇 → 子图 800 篇 → 选 88 篇成线；花费 $0.0035</sub>