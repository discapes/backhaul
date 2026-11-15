"""LoRA fine-tune of a small model on the expert experience; the loss covers only the action (the completion).

    python sft.py Qwen/Qwen3-4B-Instruct-2507 data/expert-240.jsonl out/lora
"""
import json
import sys

from datasets import Dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

model, data, out = sys.argv[1:4]
rows = [json.loads(line)["messages"] for line in open(data)]
ds = Dataset.from_list([{"prompt": m[:2], "completion": m[2:]} for m in rows]).shuffle(seed=0)
args = SFTConfig(output_dir=out, num_train_epochs=1, per_device_train_batch_size=8, gradient_accumulation_steps=2,
                 learning_rate=2e-4, lr_scheduler_type="cosine", warmup_steps=30, bf16=True, logging_steps=20,
                 save_strategy="no", max_length=4096, report_to="none")
lora = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
trainer = SFTTrainer(model=model, train_dataset=ds, args=args, peft_config=lora)
trainer.train()
trainer.save_model(out)
json.dump(trainer.state.log_history, open(f"{out}/log_history.json", "w"), indent=1)
