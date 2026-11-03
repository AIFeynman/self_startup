# 检索增强生成 RAG 研究脉络

RAG 要解决预训练模型知识固化、难溯源更新与幻觉的问题：把外部非参数化记忆（检索器）与生成模型结合。脉络上先由 DrQA/REALM/RAG 确立检索-生成范式，DPR、ColBERT、ANCE、SBERT 等把检索器从稀疏推向稠密高效；LLM 时代转向黑盒前置、自适应/主动检索与图结构增强，并伴随幻觉评测、长上下文、多模态与可信性等新方向。

**前置基础**：[BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)（2019，被引 124,949）；[Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）；[Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)（2020，被引 66,022）；[Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer](https://arxiv.org/abs/1910.10683)（2019，被引 28,232）；[GloVe: Global Vectors for Word Representation](https://www.semanticscholar.org/paper/f37e1b62a767a307c046404ca96bc140b3e68cb5)（2014，被引 35,863）；[The Probabilistic Relevance Framework: BM25 and Beyond](https://www.semanticscholar.org/paper/47ced790a563344efae66588b5fb7fe6cca29ed3)（2009，被引 6,906）

## 检索-生成范式奠基

从流水线式开放域QA出发，把检索与生成/阅读模块结合，并逐步让检索器可端到端学习，确立 RAG 的基本架构。

- **起点** [Reading Wikipedia to Answer Open-Domain Questions](https://arxiv.org/abs/1704.00051)（2017，被引 2,328）：首次把维基检索与神经阅读理解组合成开放域QA流水线
- **改进** [Latent Retrieval for Weakly Supervised Open Domain Question Answering](https://arxiv.org/abs/1906.00300)（2019，被引 1,263）：用问答对联合学习检索器与阅读器，摆脱强证据监督
- **里程碑** [REALM: Retrieval-Augmented Language Model Pre-Training](https://arxiv.org/abs/2002.08909)（2020，被引 3,602）：用掩码语言建模无监督预训练检索器，端到端跨百万文档
- **里程碑** [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)（2020，被引 20,501）：把稠密索引与seq2seq生成统一，两种生成形式达SOTA
- **改进** [Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering](https://arxiv.org/abs/2007.01282)（2020，被引 2,209）：FiD分别编码多段落再融合，生成式QA随段落数提升
- **改进** [Improving language models by retrieving from trillions of tokens](https://arxiv.org/abs/2112.04426)（2021，被引 2,016）：从万亿token库检索块并用交叉注意力，参数少25倍媲美GPT-3
- **最新** [Few-shot Learning with Retrieval Augmented Language Models](https://arxiv.org/abs/2208.03299)（2022，被引 1,471）：Atlas联合预训练检索与生成，64例few-shot即超540B模型

## 稠密检索与句向量

解决稀疏检索语义匹配弱、BERT成对计算昂贵的问题，通过双编码器、延迟交互、对比学习与负例优化，把检索器做得又快又准。

- **相关** [Billion-Scale Similarity Search with GPUs](https://arxiv.org/abs/1702.08734)（2017，被引 6,486）：设计面向GPU的高并行k-selection，优化暴力、近似与乘积量化压缩域相似度搜索，达理论峰值55%性能，比此前GPU最优快8.5倍。
- **相关** [A Broad-Coverage Challenge Corpus for Sentence Understanding through Inference](https://arxiv.org/abs/1704.05426)（2017，被引 5,378）：构建MultiNLI，43.3万条覆盖十种体裁的NLI样本，支持跨体裁域适应评测且难度显著高于SNLI。
- **起点** [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084)（2019，被引 22,085）：孪生网络句向量使相似度可预计算，检索从65小时降到5秒
- **里程碑** [Dense Passage Retrieval for Open-Domain Question Answering](https://arxiv.org/abs/2004.04906)（2020，被引 7,708）：双编码器DPR仅用少量问答对，top-20准确率超BM25 9-19%
- **改进** [ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT](https://arxiv.org/abs/2004.12832)（2020，被引 2,804）：延迟交互MaxSim媲美BERT排序而快两个数量级
- **改进** [Approximate Nearest Neighbor Negative Contrastive Learning for Dense Text Retrieval](https://arxiv.org/abs/2007.00808)（2020，被引 1,840）：用ANN索引构造真实负例，消除训练测试分布差异
- **改进** [SimCSE: Simple Contrastive Learning of Sentence Embeddings](https://arxiv.org/abs/2104.08821)（2021，被引 4,952）：dropout做无监督对比、NLI对做监督，STS显著提升
- **改进** [Unsupervised Dense Information Retrieval with Contrastive Learning](https://arxiv.org/abs/2112.09118)（2021，被引 1,843）：无监督对比训练稠密检索，BEIR多数数据集超BM25
- **相关** [BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models](https://arxiv.org/abs/2104.08663)（2021，被引 2,244）：提出BEIR异构零样本检索基准，覆盖18数据集并评10种检索系统，发现BM25稳健、重排与late-interaction零样本最佳但计算昂贵。
- **相关** [Scaling Up Visual and Vision-Language Representation Learning With Noisy Text Supervision](https://arxiv.org/abs/2102.05918)（2021，被引 6,206）：提出ALIGN，用超十亿噪声图文alt-text对训练双编码器对比对齐，规模弥补噪声，零样本分类与图文检索达当时最优。
- **最新** [Text Embeddings by Weakly-Supervised Contrastive Pre-training](https://arxiv.org/abs/2212.03533)（2022，被引 1,842）：弱监督CCPairs预训练E5，首个零样本BEIR超BM25

## 黑盒与自适应检索

LLM 时代不再改造模型架构，而是把检索文档前置给冻结模型，并让模型自行判断何时检索、检索什么，减少无差别检索的噪声与开销。

- **相关** [On the Opportunities and Risks of Foundation Models](https://arxiv.org/abs/2108.07258)（2021，被引 7,734）：系统论述基础模型的机遇与风险，提出同质化与涌现能力概念，呼吁跨学科研究理解其能力边界与社会影响。
- **改进** [When Not to Trust Language Models: Investigating Effectiveness of Parametric and Non-Parametric Memories](https://arxiv.org/abs/2212.10511)（2022，被引 1,626）：发现LLM长尾知识差，提出仅在需要时检索的自适应增强
- **改进** [Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions](https://arxiv.org/abs/2212.10509)（2022，被引 1,486）：IRCoT让检索与思维链步骤交替，减少多步问答幻觉
- **相关** [Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155)（2022，被引 25,663）：提出InstructGPT用人类示范SFT加排序RLHF微调GPT-3，1.3B模型输出比175B GPT-3更受偏好且更真实。
- **起点** [In-Context Retrieval-Augmented Language Models](https://arxiv.org/abs/2302.00083)（2023，被引 1,190）：不改架构直接前置检索文档，现成检索器即带来增益
- **改进** [REPLUG: Retrieval-Augmented Black-Box Language Models](https://arxiv.org/abs/2301.12652)（2023，被引 1,167）：REPLUG用LM监督检索器，使黑盒GPT-3语言建模提升6.3%
- **里程碑** [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)（2023，被引 3,017）：反思token让模型按需检索并自我评判，7B超ChatGPT
- **改进** [Active Retrieval Augmented Generation](https://arxiv.org/abs/2305.06983)（2023，被引 953）：FLARE用下句预测作查询，低置信处动态重新检索
- **最新** [Search-o1: Agentic Search-Enhanced Large Reasoning Models](https://arxiv.org/abs/2501.05366)（2025，被引 499）：agentic检索嵌入长推理，并用文档精炼模块降噪

## 图结构与全局增强

针对传统 RAG 只取孤立文本块、难回答全局问题与多跳关系的问题，引入实体知识图谱、社区摘要与关系路径来组织检索内容。

- **起点** [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)（2024，被引 2,495）：GraphRAG用实体图谱与社区摘要分治回答全局问题
- **改进** [Knowledge Graph-Guided Retrieval Augmented Generation](https://arxiv.org/abs/2502.06864)（2025，被引 165）：KG引导块扩展与组织，补足孤立文本块缺失的事实关系
- **改进** [PathRAG: Pruning Graph-based Retrieval Augmented Generation with Relational Paths](https://arxiv.org/abs/2502.14902)（2025，被引 105）：PathRAG检索关键关系路径并剪枝，缓解图RAG信息冗余
- **改进** [LinearRAG: Linear Graph Retrieval Augmented Generation on Large-scale Corpora](https://arxiv.org/abs/2510.10114)（2025，被引 71）：LinearRAG用无关系层次Tri-Graph，线性扩展且免关系抽取
- **最新** [GFM-RAG: Graph Foundation Model for Retrieval Augmented Generation](https://arxiv.org/abs/2502.01113)（2025，被引 64）：GFM-RAG用图基础模型推理查询-知识关系，免微调迁移

## 幻觉评测与可信性

围绕 RAG 是否真的减少幻觉、模型能否自知与溯源，建立真实性、事实核查与 RAG 能力评测基准，并延伸到可信性维度。

- **相关** [ROUGE: A Package for Automatic Evaluation of Summaries](https://www.semanticscholar.org/paper/60b05f32c32519a809f21642ef1eb3eaf3848008)（2004，被引 22,753）：提出ROUGE系列四种基于n-gram与最长公共子序列的摘要自动评测指标，成为文本摘要评测的标准工具。
- **起点** [Language Models as Knowledge Bases?](https://arxiv.org/abs/1909.01066)（2019，被引 3,409）：LAMA探针揭示预训练模型存储关系知识但覆盖有限
- **里程碑** [TruthfulQA: Measuring How Models Mimic Human Falsehoods](https://arxiv.org/abs/2109.07958)（2021，被引 4,272）：TruthfulQA暴露模型模仿错误信念，越大越不真实
- **改进** [Retrieval Augmentation Reduces Hallucination in Conversation](https://arxiv.org/abs/2104.07567)（2021，被引 1,298）：检索增强知识对话，人工评估显著降低幻觉
- **改进** [Language Models (Mostly) Know What They Know](https://arxiv.org/abs/2207.05221)（2022，被引 2,296）：P(True)/P(IK)让模型自我评估答案正确性与知识边界
- **相关** [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171)（2022，被引 8,162）：提出self-consistency解码，采样多条推理路径并边缘化选最一致答案，GSM8K提升17.9%、SVAMP提升11.0%。
- **相关** [Survey of Hallucination in Natural Language Generation](https://arxiv.org/abs/2202.03629)（2022，被引 6,581）：系统综述自然语言生成中的幻觉问题，梳理度量指标与缓解方法，并按摘要、对话、生成式问答、数据到文本、翻译分任务总结进展。
- **改进** [Benchmarking Large Language Models in Retrieval-Augmented Generation](https://arxiv.org/abs/2309.01431)（2023，被引 730）：RGB按噪声鲁棒、拒答、整合、反事实四能力评测RAG
- **改进** [SelfCheckGPT: Zero-Resource Black-Box Hallucination Detection for Generative Large Language Models](https://arxiv.org/abs/2303.08896)（2023，被引 1,389）：SelfCheckGPT用多次采样一致性做零资源黑盒幻觉检测
- **最新** [MTRAG: A Multi-Turn Conversational Benchmark for Evaluating Retrieval-Augmented Generation Systems](https://arxiv.org/abs/2501.03468)（2025，被引 98）：mtRAG补上多轮对话RAG端到端评测的空白

## 多模态与参数化增强

把 RAG 从纯文本扩展到图文视频等多模态知识，并探索把检索文档参数化注入模型，缩短上下文、加深知识整合。

- **相关** [PyTorch: An Imperative Style, High-Performance Deep Learning Library](https://arxiv.org/abs/1912.01703)（2019，被引 57,719）：介绍PyTorch的命令式Python风格设计与运行时架构，证明易用性与高性能可兼得，并展示各子系统与整体速度基准。
- **起点** [Learning Transferable Visual Models From Natural Language Supervision](https://arxiv.org/abs/2103.00020)（2021，被引 59,328）：CLIP图文对比预训练提供可检索的跨模态表示
- **相关** [Learn to Explain: Multimodal Reasoning via Thought Chains for Science Question Answering](https://arxiv.org/abs/2209.09513)（2022，被引 2,868）：提出约2.1万道多模态科学选择题基准ScienceQA并标注讲解与解释，用CoT训练语言模型，CoT使few-shot GPT-3提升1.20%、微调Unifi
- **改进** [Improved Baselines with Visual Instruction Tuning](https://arxiv.org/abs/2310.03744)（2023，被引 6,153）：LLaVA改进用CLIP-ViT+MLP连接器，1.2M数据达11基准SOTA
- **相关** [Video-MME: The First-Ever Comprehensive Evaluation Benchmark of Multi-modal LLMs in Video Analysis](https://arxiv.org/abs/2405.21075)（2024，被引 1,758）：提出首个全谱视频MLLM评测基准Video-MME，覆盖6领域30子类与长短视频，评测显示Gemini 1.5 Pro最佳达75%。
- **改进** [HM-RAG: Hierarchical Multi-Agent Multimodal Retrieval Augmented Generation](https://arxiv.org/abs/2504.12330)（2025，被引 69）：HM-RAG多智能体多源多模态检索，一致性投票融合冲突
- **最新** [Parametric Retrieval Augmented Generation](https://arxiv.org/abs/2501.15915)（2025，被引 65）：Parametric RAG把文档注入前馈网络，缩短上下文并加深整合

## 长上下文与评测基础

RAG 依赖对长文档与多段证据的利用，同时需要基准刻画模型能力边界；这条线提供长上下文建模方法与知识/推理评测基准，支撑 RAG 的检索窗口与效果度量。

- **起点** [MS MARCO: A Human Generated MAchine Reading COmprehension Dataset](https://arxiv.org/abs/1611.09268)（2016，被引 4,002）：MS MARCO用真实用户查询与网页段落，成为检索评测基础
- **改进** [TriviaQA: A Large Scale Distantly Supervised Challenge Dataset for Reading Comprehension](https://arxiv.org/abs/1705.03551)（2017，被引 4,646）：TriviaQA需跨句推理，基线远低于人类，暴露阅读难度
- **改进** [Think you have Solved Question Answering? Try ARC, the AI2 Reasoning Challenge](https://arxiv.org/abs/1803.05457)（2018，被引 6,103）：ARC小学科学选择题，神经基线难超随机，考察知识与推理
- **改进** [GLUE: A Multi-Task Benchmark and Analysis Platform for Natural Language Understanding](https://arxiv.org/abs/1804.07461)（2018，被引 9,232）：GLUE统一9项NLU任务与诊断集，暴露模型跨任务泛化不足
- **起点** [Transformer-XL: Attentive Language Models beyond a Fixed-Length Context](https://arxiv.org/abs/1901.02860)（2019，被引 4,640）：段级循环与相对位置编码突破固定上下文，长文本建模
- **起点** [Natural Questions: A Benchmark for Question Answering Research](https://www.semanticscholar.org/paper/17dbd7b72029181327732e4d11b52a08ed4630d0)（2019，被引 5,469）：Natural Questions提供真实查询与长短答案标注及稳健指标
- **改进** [HellaSwag: Can a Machine Really Finish Your Sentence?](https://arxiv.org/abs/1905.07830)（2019，被引 5,330）：HellaSwag用对抗过滤生成干扰项，人类95%而SOTA不足48%
- **改进** [Longformer: The Long-Document Transformer](https://arxiv.org/abs/2004.05150)（2020，被引 6,268）：局部窗口+全局注意力线性复杂度，长文档任务超RoBERTa
- **改进** [Measuring Massive Multitask Language Understanding](https://arxiv.org/abs/2009.03300)（2020，被引 10,379）：MMLU覆盖57学科，发现模型接近随机且不知何时答错
- **改进** [Beyond the Imitation Game: Quantifying and extrapolating the capabilities of language models](https://arxiv.org/abs/2206.04615)（2022，被引 2,715）：BIG-bench含204任务与人类基线，系统刻画规模与校准
- **相关** [PaLM: Scaling Language Modeling with Pathways](https://arxiv.org/abs/2204.02311)（2022，被引 8,578）：发布540B稠密Transformer模型PaLM，用Pathways跨6144 TPU v4训练，验证few-shot与多步推理随规模持续提升并现涌现。
- **改进** [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)（2023，被引 5,819）：揭示相关信息位于中间时性能下降，提出长上下文评测协议
- **改进** [GPQA: A Graduate-Level Google-Proof Q&A Benchmark](https://arxiv.org/abs/2311.12022)（2023，被引 3,873）：GPQA研究生级Google-proof问答，GPT-4仅39%
- **最新** [Gemini 1.5: Unlocking multimodal understanding across millions of tokens of context](https://arxiv.org/abs/2403.05530)（2024，被引 4,172）：Gemini 1.5支持百万级token，长上下文检索近完美召回
- **最新** [OlympiadBench: A Challenging Benchmark for Promoting AGI with Olympiad-Level Bilingual Multimodal Scientific Problems](https://arxiv.org/abs/2402.14008)（2024，被引 1,494）：OlympiadBench奥赛级多模态数理，GPT-4V仅17.97%

## 推荐综述

- [Retrieval-Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2312.10997)（2023，被引 4,421）
- [A Survey on RAG Meeting LLMs: Towards Retrieval-Augmented Large Language Models](https://arxiv.org/abs/2405.06211)（2024，被引 1,246）
- [Unifying Large Language Models and Knowledge Graphs: A Roadmap](https://arxiv.org/abs/2306.08302)（2023，被引 1,930）
- [Towards Trustworthy Retrieval Augmented Generation for Large Language Models: A Survey](https://arxiv.org/abs/2502.06872)（2025，被引 70）
- [Retrieval-Augmented Generation: A Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers](https://arxiv.org/abs/2506.00054)（2025，被引 76）
- [A Survey of Multimodal Retrieval-Augmented Generation](https://arxiv.org/abs/2504.08748)（2025，被引 66）

## 仍未解决

- 检索质量与生成忠实度的联合优化仍不足
- 多跳与全局问题的检索组织效率低
- RAG 在噪声与对抗输入下的鲁棒性欠缺
- 多模态与多轮场景的评测基准仍稀缺

<sub>召回 1114 篇 → 子图 1074 篇 → 选 88 篇成线；花费 $0.0036</sub>