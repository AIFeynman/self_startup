# 后训练 研究脉络

后训练旨在将预训练语言模型对齐到人类意图与安全规范，并激发推理等高级能力。其演进经历三阶段：早期以指令微调（FLAN、LIMA）和基于人类偏好的强化学习（RLHF，InstructGPT）奠定范式；随后DPO等直接偏好优化简化流程，开源模型（Llama 2、Qwen）推动规模化；近期以可验证奖励的强化学习（GRPO、DeepSeek-R1）激发推理，并探索SFT与RL的泛化差异、奖励模型与过程监督。

**前置基础**：[Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347)（2017，被引 33,097）；[Deep Reinforcement Learning from Human Preferences](https://arxiv.org/abs/1706.03741)（2017，被引 6,323）；[Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)（2020，被引 66,022）；[BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)（2019，被引 124,949）；[Chain of Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903)（2022，被引 23,524）；[LLaMA: Open and Efficient Foundation Language Models](https://arxiv.org/abs/2302.13971)（2023，被引 22,487）

## 指令微调与数据构建

从FLAN验证指令微调可提升零样本泛化，到Self-Instruct自生成指令数据、LIMA证明少量精选数据即可对齐，再到Evol-Instruct提升指令复杂度，逐步降低对人工标注的依赖并提升数据效率。

- **起点** [Finetuned Language Models Are Zero-Shot Learners](https://arxiv.org/abs/2109.01652)（2021，被引 5,585）：提出指令微调FLAN，60+任务微调显著提升零样本泛化
- **改进** [Self-Instruct: Aligning Language Models with Self-Generated Instructions](https://arxiv.org/abs/2212.10560)（2022，被引 3,869）：用模型自生成指令数据，摆脱人工指令依赖
- **里程碑** [LIMA: Less Is More for Alignment](https://arxiv.org/abs/2305.11206)（2023，被引 1,554）：仅1000条精选指令即达GPT-4级对话质量，揭示数据质量重于数量
- **改进** [WizardLM: Empowering Large Pre-Trained Language Models to Follow Complex Instructions](https://arxiv.org/abs/2304.12244)（2023，被引 1,360）：Evol-Instruct演化指令复杂度，提升复杂指令遵循能力
- **改进** [The Flan Collection: Designing Data and Methods for Effective Instruction Tuning](https://arxiv.org/abs/2301.13688)（2023，被引 1,028）：系统消融指令微调设计，任务平衡与混合提示提升效果
- **最新** [LIMO: Less is More for Reasoning](https://arxiv.org/abs/2502.03387)（2025，被引 570）：LIMO用1%数据SFT激发强推理，提出少即是多假设

## RLHF偏好优化

从人类偏好学习奖励模型并用PPO优化（InstructGPT），到分析奖励过优化与KL约束，再到DPO将奖励参数化实现闭式偏好优化，SimPO进一步去参考模型，降低RLHF复杂度与不稳定性。

- **起点** [Fine-Tuning Language Models from Human Preferences](https://arxiv.org/abs/1909.08593)（2019，被引 2,836）：首次将人类偏好奖励学习用于语言模型微调
- **改进** [Learning to summarize from human feedback](https://arxiv.org/abs/2009.01325)（2020，被引 3,637）：用人类比较训练奖励模型+PPO，摘要超越人类参考
- **里程碑** [Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155)（2022，被引 25,663）：InstructGPT确立SFT+RM+PPO三阶段RLHF范式
- **改进** [Training a Helpful and Harmless Assistant with Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2204.05862)（2022，被引 4,475）：系统研究RLHF训练有帮助且无害助手，分析KL-奖励关系
- **改进** [Scaling Laws for Reward Model Overoptimization](https://arxiv.org/abs/2210.10760)（2022，被引 1,453）：量化奖励过优化，揭示Goodhart效应与缩放规律
- **里程碑** [Direct Preference Optimization: Your Language Model is Secretly a Reward Model](https://arxiv.org/abs/2305.18290)（2023，被引 11,470）：DPO将RLHF转为分类损失，无需显式奖励模型与RL
- **改进** [SimPO: Simple Preference Optimization with a Reference-Free Reward](https://arxiv.org/abs/2405.14734)（2024，被引 1,264）：SimPO去参考模型并用平均对数概率作奖励，更简洁高效

## 可验证奖励强化学习

以GRPO替代PPO降低内存，DeepSeek-R1用纯RL+规则奖励激发自我反思等推理模式，DAPO等开源系统提升大规模RL稳定性，并探索RL在视觉任务与搜索中的扩展。

- **起点** [DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models](https://arxiv.org/abs/2402.03300)（2024，被引 10,680）：提出GRPO替代PPO，数学推理达51.7%
- **里程碑** [DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning](https://arxiv.org/abs/2501.12948)（2025，被引 5,976）：纯RL+可验证奖励激发推理涌现，超越监督学习
- **改进** [DAPO: An Open-Source LLM Reinforcement Learning System at Scale](https://arxiv.org/abs/2503.14476)（2025，被引 3,127）：DAPO开源大规模RL系统，解耦裁剪与动态采样提升稳定性
- **改进** [Open-Reasoner-Zero: An Open Source Approach to Scaling Up Reinforcement Learning on the Base Model](https://arxiv.org/abs/2503.24290)（2025，被引 558）：Open-Reasoner-Zero用无KL的PPO复现R1-Zero缩放
- **变体** [Search-R1: Training LLMs to Reason and Leverage Search Engines with Reinforcement Learning](https://arxiv.org/abs/2503.09516)（2025，被引 1,752）：Search-R1将RL扩展到多轮检索推理
- **变体** [VLM-R1: A Stable and Generalizable R1-style Large Vision-Language Model](https://arxiv.org/abs/2504.07615)（2025，被引 558）：VLM-R1将R1式规则奖励RL迁移到视觉语言任务

## 奖励模型与过程监督

从结果监督转向过程监督（PRM800K），Math-Shepherd自动构造步骤级监督，GenRM用生成式验证，PRIME用隐式过程奖励在线更新，并出现RewardBench等系统评测基准。

- **起点** [Let's Verify Step by Step](https://arxiv.org/abs/2305.20050)（2023，被引 5,294）：系统比较过程与结果监督，过程监督显著更优并开源PRM800K
- **改进** [Math-Shepherd: Verify and Reinforce LLMs Step-by-step without Human Annotations](https://arxiv.org/abs/2312.08935)（2023，被引 1,313）：Math-Shepherd自动构造步骤级监督，无需人工标注
- **改进** [Generative Verifiers: Reward Modeling as Next-Token Prediction](https://arxiv.org/abs/2408.15240)（2024，被引 572）：GenRM用下一token预测做生成式验证，Best-of-N大幅提升
- **改进** [Process Reinforcement through Implicit Rewards](https://arxiv.org/abs/2502.01456)（2025，被引 499）：PRIME用隐式过程奖励在线更新，仅需结果标签
- **变体** [RewardBench: Evaluating Reward Models for Language Modeling](https://arxiv.org/abs/2403.13787)（2024，被引 705）：RewardBench系统评测奖励模型，揭示拒答与推理缺陷
- **最新** [RewardBench 2: Advancing Reward Model Evaluation](https://arxiv.org/abs/2506.01937)（2025，被引 163）：RewardBench 2用新人类prompt提升区分度并与下游表现相关

## SFT与RL泛化对比

系统比较SFT与RL在后训练中的作用：SFT倾向记忆但稳定输出格式，RL泛化更好；RLVR是否真正扩展推理能力存疑，蒸馏可扩展能力；on-policy数据减少遗忘。

- **起点** [SFT Memorizes, RL Generalizes: A Comparative Study of Foundation Model Post-training](https://arxiv.org/abs/2501.17161)（2025，被引 781）：对比SFT与RL，发现RL泛化更好而SFT倾向记忆
- **改进** [Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?](https://arxiv.org/abs/2504.13837)（2025，被引 1,205）：发现RLVR未产生新推理模式，蒸馏才真正扩展能力
- **改进** [Retaining by Doing: The Role of On-Policy Data in Mitigating Forgetting](https://arxiv.org/abs/2510.18874)（2025，被引 104）：揭示RL因on-policy数据mode-seeking特性遗忘更少
- **改进** [On-Policy RL Meets Off-Policy Experts: Harmonizing Supervised Fine-Tuning and Reinforcement Learning via Dynamic Weighting](https://arxiv.org/abs/2508.11408)（2025，被引 116）：CHORD动态加权协调SFT与RL，稳定训练并防过拟合

## AI反馈与可扩展监督

为降低人类标注成本，Constitutional AI用原则自我批判与RLAIF训练无害助手，RLAIF验证AI反馈可替代人类反馈，弱到强泛化与辩论探索超人类监督。

- **起点** [Constitutional AI: Harmlessness from AI Feedback](https://arxiv.org/abs/2212.08073)（2022，被引 3,959）：Constitutional AI用原则自我批判与AI反馈，无需人工有害标注
- **改进** [RLAIF vs. RLHF: Scaling Reinforcement Learning from Human Feedback with AI Feedback](https://arxiv.org/abs/2309.00267)（2023，被引 770）：RLAIF验证AI反馈在摘要与对话上媲美RLHF
- **改进** [Weak-to-Strong Generalization: Eliciting Strong Capabilities With Weak Supervision](https://arxiv.org/abs/2312.09390)（2023，被引 591）：研究弱到强泛化，弱监督可激发强模型部分能力
- **变体** [AI safety via debate](https://arxiv.org/abs/1805.00899)（2018，被引 513）：提出AI辩论框架，探索可扩展监督

## 多模态后训练

将指令微调与偏好优化扩展到视觉语言模型：LLaVA用GPT-4生成多模态指令数据，InstructBLIP引入指令感知Q-Former，InternVL3用混合偏好优化统一训练。

- **起点** [Visual Instruction Tuning](https://arxiv.org/abs/2304.08485)（2023，被引 11,807）：用GPT-4生成多模态指令数据，提出LLaVA视觉指令微调
- **改进** [Improved Baselines with Visual Instruction Tuning](https://arxiv.org/abs/2310.03744)（2023，被引 6,153）：系统研究LMM设计选择，MLP连接器+学术VQA数据达SOTA
- **改进** [InstructBLIP: Towards General-purpose Vision-Language Models with Instruction Tuning](https://arxiv.org/abs/2305.06500)（2023，被引 4,182）：InstructBLIP指令感知Q-Former，13个零样本数据集SOTA
- **最新** [InternVL3: Exploring Advanced Training and Test-Time Recipes for Open-Source Multimodal Models](https://arxiv.org/abs/2504.10479)（2025，被引 2,058）：InternVL3原生多模态预训练+混合偏好优化，开源SOTA

## 开源模型后训练实践

开源模型系列（Llama 2、Qwen、GLM、Qwen2.5）将SFT+RLHF流程工程化，并引入多阶段RL、百万级SFT与工具调用，推动后训练规模化落地。

- **起点** [Llama 2: Open Foundation and Fine-Tuned Chat Models](https://arxiv.org/abs/2307.09288)（2023，被引 18,914）：Llama 2详述SFT+RLHF+安全改进，开源对话模型可替代闭源
- **改进** [Qwen Technical Report](https://arxiv.org/abs/2309.16609)（2023，被引 4,564）：Qwen系列用RLHF对齐中英双语模型，并衍生代码数学专用模型
- **改进** [ChatGLM: A Family of Large Language Models from GLM-130B to GLM-4 All Tools](https://arxiv.org/abs/2406.12793)（2024，被引 1,884）：GLM-4多阶段SFT+RLHF对齐，支持自主工具调用
- **改进** [Qwen2.5 Technical Report](https://arxiv.org/abs/2412.15115)（2024，被引 5,760）：Qwen2.5用百万级SFT与多阶段RL，72B媲美5倍大模型
- **变体** [Qwen2.5-Math Technical Report: Toward Mathematical Expert Model via Self-Improvement](https://arxiv.org/abs/2409.12122)（2024，被引 1,231）：Qwen2.5-Math用奖励模型迭代SFT数据并RL，专攻数学推理

## 后训练系统与效率

针对RLHF训练开销大、流程复杂的问题，HybridFlow用混合控制器与零冗余重分片提升吞吐，LoRA以低秩适配降低微调成本，知识蒸馏将大模型能力压缩到小模型。

- **起点** [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)（2021，被引 25,273）：LoRA冻结预训练权重注入低秩矩阵，大幅降低微调成本
- **改进** [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)（2015，被引 27,519）：知识蒸馏用软目标压缩集成知识，为后训练蒸馏奠基
- **最新** [HybridFlow: A Flexible and Efficient RLHF Framework](https://arxiv.org/abs/2409.19256)（2024，被引 2,647）：HybridFlow混合单/多控制器RLHF框架，吞吐提升1.53-20.57倍

## 偏好数据与评测

为降低人类反馈数据成本并提升评测可信度，OpenAssistant众包构建开放对话语料，WebGPT用浏览环境收集人类反馈，GPT-4技术报告展示对齐后训练效果，MT-Bench提供LLM-as-a-judge评测。

- **起点** [OpenAssistant Conversations - Democratizing Large Language Model Alignment](https://arxiv.org/abs/2304.07327)（2023，被引 983）：OpenAssistant众包多语言对话语料，开放对齐研究数据
- **改进** [WebGPT: Browser-assisted question-answering with human feedback](https://arxiv.org/abs/2112.09332)（2021，被引 2,183）：WebGPT用浏览环境+人类反馈训练问答，答案胜率超人类示范
- **里程碑** [GPT-4 Technical Report](https://arxiv.org/abs/2303.08774)（2023，被引 28,245）：GPT-4用RLHF后训练对齐，模拟律师考试进入前10%
- **改进** [Judging LLM-as-a-judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685)（2023，被引 12,797）：MT-Bench与Chatbot Arena系统评测LLM-as-a-judge偏差

## 推荐综述

- [A Survey of Large Language Models](https://arxiv.org/abs/2303.18223)（2023，被引 5,216）
- [Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2504.12501)（2025，被引 125）

## 仍未解决

- RLVR是否真正扩展推理能力仍存争议
- 奖励模型过优化与reward hacking难根治
- SFT与RL的最优组合策略尚不明确
- 多模态后训练的统一范式尚未形成

<sub>召回 1214 篇 → 子图 800 篇 → 选 88 篇成线；花费 $0.0039</sub>