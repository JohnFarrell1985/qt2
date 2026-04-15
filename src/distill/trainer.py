"""学生模型分层训练 (P2-20)

三阶段渐进式训练:
- Phase 0: SetFit 冷启动 (8 样本/类, ~30s)
- Phase 1: LoRA SFT 主训练 (easy_set, 1-3h)
- Phase 2: DPO 偏好对齐 (hard_set, 0.5-1h)

所有 HuggingFace 依赖延迟导入, CI/本地无 GPU 时优雅降级。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class StagedTrainer:
    """三阶段渐进式训练: SetFit冷启动 → LoRA SFT → DPO强化"""

    def __init__(self, student_name: str = "finbert2-base", lora_rank: int = 16):
        self.student_name = student_name
        self.lora_rank = lora_rank

    def phase0_setfit(self, few_shot_examples: Dict[str, list]) -> Any:
        """Phase 0: 8样本/类冷启动 (~30秒)

        Args:
            few_shot_examples: {"positive": [...], "negative": [...], "neutral": [...]}

        Returns:
            SetFitModel (trained)
        """
        try:
            from setfit import SetFitModel, SetFitTrainer
            from datasets import Dataset
        except ImportError:
            raise RuntimeError("setfit 或 datasets 未安装。请运行: uv pip install setfit datasets")

        texts, labels = [], []
        for label, examples in few_shot_examples.items():
            for ex in examples:
                texts.append(ex)
                labels.append(label)

        dataset = Dataset.from_dict({"text": texts, "label": labels})
        model = SetFitModel.from_pretrained(self.student_name)
        trainer = SetFitTrainer(model=model, train_dataset=dataset)
        trainer.train()
        logger.info("Phase 0 SetFit 冷启动完成: %d 样本", len(texts))
        return model

    def phase1_lora_sft(self, easy_dataset, base_model=None) -> Any:
        """Phase 1: LoRA 微调 — 显存仅需 4-6GB (GTX 1660+ 可用)

        Args:
            easy_dataset: HuggingFace Dataset (text, label)
            base_model: 可选预训练模型, None 则从 student_name 加载

        Returns:
            LoRA-merged model
        """
        try:
            from peft import LoraConfig, get_peft_model
            from transformers import AutoModelForSequenceClassification, Trainer, TrainingArguments
        except ImportError:
            raise RuntimeError("peft/transformers 未安装。请运行: uv pip install peft transformers")

        model = AutoModelForSequenceClassification.from_pretrained(
            self.student_name, num_labels=3,
        )
        lora_config = LoraConfig(
            r=self.lora_rank,
            lora_alpha=32,
            target_modules=["query", "value"],
            task_type="SEQ_CLS",
        )
        model = get_peft_model(model, lora_config)
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in model.parameters())
        logger.info("LoRA: 可训练参数 %d / %d (%.2f%%)", trainable, total, trainable / total * 100)

        args = TrainingArguments(
            output_dir="models/distilled/checkpoints",
            num_train_epochs=3,
            per_device_train_batch_size=16,
            learning_rate=2e-5,
            logging_steps=50,
            save_strategy="epoch",
            fp16=True,
        )
        trainer = Trainer(model=model, args=args, train_dataset=easy_dataset)
        trainer.train()
        logger.info("Phase 1 LoRA SFT 训练完成")
        return model

    def phase2_dpo(self, hard_dataset, model) -> Any:
        """Phase 2: DPO 偏好对齐 — 利用教师分歧构造偏好对

        Args:
            hard_dataset: 偏好对数据集 (text, chosen, rejected)
            model: Phase 1 输出的模型

        Returns:
            DPO-aligned model
        """
        try:
            from trl import DPOTrainer, DPOConfig
        except ImportError:
            raise RuntimeError("trl 未安装。请运行: uv pip install trl>=0.8")

        dpo_config = DPOConfig(
            beta=0.1,
            learning_rate=5e-6,
            output_dir="models/distilled/dpo",
        )
        trainer = DPOTrainer(
            model=model,
            train_dataset=hard_dataset,
            args=dpo_config,
        )
        trainer.train()
        logger.info("Phase 2 DPO 训练完成")
        return model
