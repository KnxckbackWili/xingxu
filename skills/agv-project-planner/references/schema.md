# 输出结构

输出顶层对象必须包含 `draft`、`missing_fields`、`conflicts`、`assumptions`、`change_summary`。

`draft` 仅包含：

```json
{
  "schedule_suggestions": [
    {
      "task_name": "必须引用资料中的已有任务名称",
      "recommended_date": "YYYY-MM-DD 或空字符串",
      "assignee": "已有人员姓名或空字符串",
      "reason": "依赖、能力、停机窗口或工作量依据",
      "confidence": "high|medium|low"
    }
  ],
  "risks": ["排程风险或冲突"]
}
```

这里只输出建议，不输出系统 ID，不改动已锁定日程，不把项目准备事项生成成排程任务。
