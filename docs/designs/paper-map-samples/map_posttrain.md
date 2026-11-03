# 后训练 研究脉络

后训练旨在将预训练语言模型对齐到人类意图与偏好，解决输出不真实、有害、不遵循指令及复杂推理弱等问题。其演进经历三阶段：早期以指令微调（FLAN、T0）和人类偏好强化学习（RLHF）奠定基础；随后DPO等直接偏好优化简化流程，并出现大量变体与开源配方；2024年后，可验证奖励强化学习（RLVR）成为推理模型后训练核心，同时蒸馏、过程奖励模型与多模态后训练蓬勃发展。

**前置基础**：[Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347)（2017，被引 33,097）；[Deep Reinforcement Learning from Human Preferences](https://arxiv.org/abs/1706.03741)（2017，被引 6,323）；[Attention is All you Need](https://arxiv.org/abs/1706.03762)（2017，被引 201,064）；[Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)（2015，被引 27,519）；[Chain of Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903)（2022，被引 23,524）；[LLaMA: Open and Efficient Foundation Language Models](https://arxiv.org/abs/2302.13971)（2023，被引 22,487）

## 指令微调与数据自举

解决人工指令数据稀缺与零样本泛化弱的问题。从多任务指令微调（FLAN、T0）出发，发展到自生成指令（Self-Instruct、Evol-Instruct）和GPT-4生成数据，并探索数据规模与质量（LIMA、LIMO）。

- **相关** [Universal Language Model Fine-tuning for Text Classification](https://www.semanticscholar.org/paper/1e077413b25c4d34945cc2707e17e46ed4fe784a)（2018，被引 4,443）：提出ULMFiT通用语言模型微调方法，用判别式微调、斜三角学习率和逐层解冻，在六个文本分类任务上误差降低18-24%，100样本可媲美百倍数据从头训练。
- **起点** [Finetuned Language Models Are Zero-Shot Learners](https://arxiv.org/abs/2109.01652)（2021，被引 5,585）：提出指令微调FLAN，零样本超越更大模型
- **改进** [Multitask Prompted Training Enables Zero-Shot Task Generalization](https://arxiv.org/abs/2110.08207)（2021，被引 2,116）：多任务prompted训练T0，验证显式多任务诱导泛化
- **里程碑** [Scaling Instruction-Finetuned Language Models](https://arxiv.org/abs/2210.11416)（2022，被引 4,562）：系统缩放指令微调任务数、模型规模与CoT数据
- **改进** [Self-Instruct: Aligning Language Models with Self-Generated Instructions](https://arxiv.org/abs/2212.10560)（2022，被引 3,869）：自生成指令数据，降低人工依赖
- **改进** [WizardLM: Empowering Large Pre-Trained Language Models to Follow Complex Instructions](https://arxiv.org/abs/2304.12244)（2023，被引 1,360）：Evol-Instruct演化指令复杂度，提升复杂指令遵循
- **变体** [Instruction Tuning with GPT-4](https://arxiv.org/abs/2304.03277)（2023，被引 884）：用GPT-4生成高质量中英文指令数据
- **里程碑** [LIMA: Less Is More for Alignment](https://arxiv.org/abs/2305.11206)（2023，被引 1,554）：LIMA证明千条精选指令即可有效对齐
- **相关** [Qwen Technical Report](https://arxiv.org/abs/2309.16609)（2023，被引 4,564）：发布 Qwen 系列技术报告，含基础预训练模型与经 RLHF 对齐的 Qwen-Chat，并衍生代码与数学专用模型，性能接近闭源模型。
- **最新** [LIMO: Less is More for Reasoning](https://arxiv.org/abs/2502.03387)（2025，被引 570）：LIMO用1%数据激发强数学推理，提出少即是多假设
- **相关** [SFT Memorizes, RL Generalizes: A Comparative Study of Foundation Model Post-training](https://arxiv.org/abs/2501.17161)（2025，被引 781）：用GeneralPoints与V-IRL对比SFT与RL，发现RL在文本与视觉变体上泛化更好，SFT倾向记忆但为RL稳定输出格式所必需。

## RLHF与偏好优化

解决奖励难以定义与对齐不稳定问题。从人类偏好奖励学习（PPO）起步，InstructGPT确立SFT+RLHF范式，DPO简化流程，后续出现SimPO、REINFORCE式简化及RLAIF等变体，并关注奖励过优化。

- **起点** [Fine-Tuning Language Models from Human Preferences](https://arxiv.org/abs/1909.08593)（2019，被引 2,836）：首次将人类偏好奖励学习用于语言任务
- **改进** [Learning to summarize from human feedback](https://arxiv.org/abs/2009.01325)（2020，被引 3,637）：用偏好比较训练奖励模型并PPO微调摘要
- **里程碑** [Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155)（2022，被引 25,663）：InstructGPT确立SFT+RLHF范式，1.3B超175B
- **改进** [Training a Helpful and Harmless Assistant with Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2204.05862)（2022，被引 4,475）：系统研究有用性与无害性RLHF，揭示KL-奖励关系
- **变体** [Scaling Laws for Reward Model Overoptimization](https://arxiv.org/abs/2210.10760)（2022，被引 1,453）：定量刻画奖励模型过优化与缩放规律
- **里程碑** [Direct Preference Optimization: Your Language Model is Secretly a Reward Model](https://arxiv.org/abs/2305.18290)（2023，被引 11,470）：DPO将RLHF简化为分类损失，无需显式奖励模型
- **变体** [RLAIF vs. RLHF: Scaling Reinforcement Learning from Human Feedback with AI Feedback](https://arxiv.org/abs/2309.00267)（2023，被引 770）：RLAIF用AI反馈替代人类反馈，效果相当
- **相关** [OpenAssistant Conversations - Democratizing Large Language Model Alignment](https://arxiv.org/abs/2304.07327)（2023，被引 983）：发布OpenAssistant Conversations，13.5万条消息、46万质量评分、35种语言的众包对话语料，训练模型在标准基准上稳定提升。
- **相关** [AlpacaFarm: A Simulation Framework for Methods that Learn from Human Feedback](https://arxiv.org/abs/2305.14387)（2023，被引 971）：提出AlpacaFarm用LLM模拟人类反馈并自动评测，提供PPO/DPO等参考实现，模拟排名与真实人类数据排名一致。
- **改进** [SimPO: Simple Preference Optimization with a Reference-Free Reward](https://arxiv.org/abs/2405.14734)（2024，被引 1,264）：SimPO去参考模型并加目标奖励边际，提升DPO
- **改进** [Back to Basics: Revisiting REINFORCE Style Optimization for Learning from Human Feedback in LLMs](https://arxiv.org/abs/2402.14740)（2024，被引 791）：简化REINFORCE式优化，超越PPO与DPO且成本更低
- **最新** [TÜLU 3: Pushing Frontiers in Open Language Model Post-Training](https://arxiv.org/abs/2411.15124)（2024，被引 1,077）：Tulu 3全开放后训练配方，结合SFT、DPO与RLVR

## 推理强化学习

解决复杂推理依赖人工标注与能力不足问题。从STaR自举推理链开始，DeepSeekMath提出GRPO降低PPO开销，DeepSeek-R1用纯RL激发长思维链，后续DAPO、Kimi k1.5等改进RL稳定性与规模，并出现对RLVR能力的反思。

- **起点** [STaR: Bootstrapping Reasoning With Reasoning](https://arxiv.org/abs/2203.14465)（2022，被引 1,223）：STaR自举推理链并迭代微调，低成本提升推理
- **里程碑** [DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models](https://arxiv.org/abs/2402.03300)（2024，被引 10,680）：提出GRPO替代PPO，大幅降低RL内存开销
- **相关** [Qwen2.5-Math Technical Report: Toward Mathematical Expert Model via Self-Improvement](https://arxiv.org/abs/2409.12122)（2024，被引 1,231）：发布 Qwen2.5-Math 系列数学专家模型，贯穿预训练、后训练与推理的自改进流程，用奖励模型迭代 SFT 数据并做 RL，支持中英与 TIR。
- **相关** [OpenAI o1 System Card](https://www.semanticscholar.org/paper/985298bd0b6f4c84ab34bb15cfed0b092f43b83a)（2024，被引 2,139）：OpenAI o1系统卡，介绍用大规模强化学习训练长思维链推理模型，并给出能力与安全评测结果。
- **相关** [Qwen2.5 Technical Report](https://arxiv.org/abs/2412.15115)（2024，被引 5,760）：发布 Qwen2.5 系列，预训练数据扩至 18T token，后训练用百万级 SFT 与多阶段 RL，开源旗舰 72B-Instruct 性能媲美约 5 倍大
- **里程碑** [DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning](https://arxiv.org/abs/2501.12948)（2025，被引 5,976）：DeepSeek-R1纯RL激励自我反思与验证等推理模式
- **改进** [DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning](https://www.semanticscholar.org/paper/bf76cb3bd7a54c60138f9523ffb462a486c4807b)（2025，被引 6,378）：R1加冷启动与多阶段训练，提升可读性与稳定性
- **改进** [DAPO: An Open-Source LLM Reinforcement Learning System at Scale](https://arxiv.org/abs/2503.14476)（2025，被引 3,127）：DAPO开源大规模RL系统，解耦裁剪与动态采样
- **改进** [Kimi k1.5: Scaling Reinforcement Learning with LLMs](https://arxiv.org/abs/2501.12599)（2025，被引 1,146）：Kimi k1.5长上下文RL，不依赖MCTS与PRM
- **变体** [Understanding R1-Zero-Like Training: A Critical Perspective](https://arxiv.org/abs/2503.20783)（2025，被引 1,555）：剖析R1-Zero，提出Dr. GRPO纠正长度偏差
- **最新** [Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?](https://arxiv.org/abs/2504.13837)（2025，被引 1,205）：质疑RLVR未扩展推理边界，蒸馏才真正扩展能力
- **相关** [Open-Reasoner-Zero: An Open Source Approach to Scaling Up Reinforcement Learning on the Base Model](https://arxiv.org/abs/2503.24290)（2025，被引 558）：开源Open-Reasoner-Zero，用无KL的PPO+规则奖励复现R1-Zero缩放现象，仅1/10步数超越基线。

## 过程奖励与验证器

解决多步推理中间错误与结果监督不足问题。从训练验证器重排序开始，过程监督（PRM800K）证明步骤级反馈更优，Math-Shepherd实现自动过程标注，PRIME在线更新隐式过程奖励，GenRM用生成式验证器统一验证与生成。

- **起点** [Training Verifiers to Solve Math Word Problems](https://arxiv.org/abs/2110.14168)（2021，被引 11,892）：GSM8K基准与训练验证器重排序候选解
- **里程碑** [Let's Verify Step by Step](https://arxiv.org/abs/2305.20050)（2023，被引 5,294）：系统比较过程与结果监督，开源PRM800K
- **改进** [Math-Shepherd: Verify and Reinforce LLMs Step-by-step without Human Annotations](https://arxiv.org/abs/2312.08935)（2023，被引 1,313）：Math-Shepherd自动构造步骤级监督，无需人工标注
- **相关** [Llama 2: Open Foundation and Fine-Tuned Chat Models](https://arxiv.org/abs/2307.09288)（2023，被引 18,914）：发布7B-70B预训练与对话模型Llama 2-Chat，详述SFT、RLHF与安全改进流程，多数基准超越开源对话模型，人类评测可替代闭源模型。
- **相关** [GPT-4 Technical Report](https://arxiv.org/abs/2303.08774)（2023，被引 28,245）：发布GPT-4多模态技术报告，用可预测缩放的基础设施训练并用对齐后训练，模拟律师考试进入前10%。
- **变体** [Generative Verifiers: Reward Modeling as Next-Token Prediction](https://arxiv.org/abs/2408.15240)（2024，被引 572）：GenRM用下一token预测做生成式验证器
- **变体** [RewardBench: Evaluating Reward Models for Language Modeling](https://arxiv.org/abs/2403.13787)（2024，被引 705）：RewardBench系统评测奖励模型，揭示其缺陷
- **相关** [HybridFlow: A Flexible and Efficient RLHF Framework](https://arxiv.org/abs/2409.19256)（2024，被引 2,647）：提出HybridFlow混合单/多控制器RLHF框架，配3D-HybridEngine零冗余重分片，吞吐提升1.53-20.57倍。
- **改进** [Process Reinforcement through Implicit Rewards](https://arxiv.org/abs/2502.01456)（2025，被引 499）：PRIME仅用结果标签在线更新隐式过程奖励

## 对齐与安全

解决无害性依赖人工标注与可扩展监督问题。从RLHF有用无害训练出发，Constitutional AI用原则自我批判与RLAIF减少人工标注，SELF-ALIGN用极少监督自对齐，弱到强泛化探索超人类模型监督。

- **起点** [Training a Helpful and Harmless Assistant with Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2204.05862)（2022，被引 4,475）：RLHF训练有用且无害助手，揭示KL-奖励关系
- **里程碑** [Constitutional AI: Harmlessness from AI Feedback](https://arxiv.org/abs/2212.08073)（2022，被引 3,959）：Constitutional AI用原则与AI反馈实现无害对齐
- **改进** [Principle-Driven Self-Alignment of Language Models from Scratch with Minimal Human Supervision](https://arxiv.org/abs/2305.03047)（2023，被引 478）：SELF-ALIGN用少量原则自对齐，极少人工监督
- **最新** [Weak-to-Strong Generalization: Eliciting Strong Capabilities With Weak Supervision](https://arxiv.org/abs/2312.09390)（2023，被引 591）：弱到强泛化，探索弱监督激发强模型能力

## 蒸馏与高效后训练

解决大模型部署成本高与小模型能力不足问题。从知识蒸馏软目标开始，序列级蒸馏与TinyBERT等压缩BERT，Zephyr用蒸馏DPO对齐小模型，GKD解决分布不匹配，Qwen3用蒸馏将推理能力迁移到小模型。

- **起点** [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)（2015，被引 27,519）：提出知识蒸馏，用软目标压缩集成知识
- **改进** [DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter](https://arxiv.org/abs/1910.01108)（2019，被引 10,948）：DistilBERT预训练蒸馏，参数减40%保留97%能力
- **改进** [MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers](https://arxiv.org/abs/2002.10957)（2020，被引 2,920）：MiniLM深度自注意力蒸馏，高效压缩Transformer
- **变体** [Zephyr: Direct Distillation of LM Alignment](https://arxiv.org/abs/2310.16944)（2023，被引 680）：Zephyr用蒸馏DPO对齐7B小模型，超越Llama2-70B
- **改进** [On-Policy Distillation of Language Models: Learning from Self-Generated Mistakes](https://arxiv.org/abs/2306.13649)（2023，被引 1,239）：GKD在自生成序列上蒸馏，缓解分布不匹配
- **最新** [Qwen3 Technical Report](https://arxiv.org/abs/2505.09388)（2025，被引 9,881）：Qwen3用蒸馏将大模型推理能力迁移到小模型

## 多模态后训练

解决视觉语言模型指令跟随与推理能力弱问题。从LLaVA视觉指令微调开始，LLaVA-1.5改进连接器与数据效率，InternVL3原生多模态预训练与混合偏好优化，Visual-RFT与VLM-R1将可验证奖励RL扩展到视觉任务。

- **起点** [Visual Instruction Tuning](https://arxiv.org/abs/2304.08485)（2023，被引 11,807）：LLaVA用GPT-4生成多模态指令数据做视觉指令微调
- **改进** [Improved Baselines with Visual Instruction Tuning](https://arxiv.org/abs/2310.03744)（2023，被引 6,153）：LLaVA-1.5改进连接器与数据，提升VLM数据效率
- **里程碑** [InternVL3: Exploring Advanced Training and Test-Time Recipes for Open-Source Multimodal Models](https://arxiv.org/abs/2504.10479)（2025，被引 2,058）：InternVL3原生多模态预训练与混合偏好优化
- **变体** [Visual-RFT: Visual Reinforcement Fine-Tuning](https://arxiv.org/abs/2503.01785)（2025，被引 595）：Visual-RFT将可验证奖励RL扩展到视觉感知任务
- **最新** [VLM-R1: A Stable and Generalizable R1-style Large Vision-Language Model](https://arxiv.org/abs/2504.07615)（2025，被引 558）：VLM-R1将R1式规则奖励RL用于VLM，泛化超SFT

## 推荐综述

- [A Survey of Large Language Models](https://arxiv.org/abs/2303.18223)（2023，被引 5,216）
- [Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2504.12501)（2025，被引 125）

## 仍未解决

- RLVR是否真正扩展推理能力仍存争议
- 奖励模型过优化与奖励欺骗难以根治
- 后训练中的灾难性遗忘机制尚不明确
- 多模态与推理后训练的统一配方缺失

<sub>召回 1337 篇 → 子图 1313 篇 → 选 88 篇成线；花费 $0.004</sub>