# 提交约定

新提交使用 Conventional Commits 格式：

```text
<type>(<scope>): <summary>
```

- `type`：`feat`（新功能）、`fix`（修复）、`docs`（文档）、`test`（测试）、`refactor`（不改变行为的重构）、`chore`（工具或维护）。
- `scope`：使用稳定的功能区域，例如 `control`、`receivers`、`firmware`、`experiment`；不必逐文件命名。
- `summary`：一句话说明本提交实际完成的变化，使用祈使语气；不要只写“更新代码”“修复问题”或实验日期。
- 需要说明约束、迁移或验证时，在空行后的正文写清楚。破坏兼容性的改动使用 `!` 并在正文标明影响。
- 按可独立理解的功能迭代拆分提交；实现、配套测试可放在同一提交，跨阶段文档可单独提交。不要把实验原始数据、无关清理和新功能混在一条提交里。

示例：`feat(control): add sample-domain command engine and replay`、`fix(receivers): reject mismatched control run IDs`、`docs(experiment): define multi-task control validation`。
