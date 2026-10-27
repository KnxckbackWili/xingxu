# 输出结构

输出顶层对象必须包含 `draft`、`missing_fields`、`conflicts`、`assumptions`、`change_summary`。

`draft` 仅包含：

```json
{
  "issues": [
    {
      "title": "简洁的问题标题",
      "description": "已知现象、影响范围和现有证据",
      "issue_type": "hardware|software|environment|process|safety|other",
      "severity": "critical|high|medium|low",
      "task_id": null,
      "assignee_id": null,
      "extra": {}
    }
  ]
}
```

不得猜测系统用户 ID。具体单车故障应写入 `missing_fields`，提示用户前往车辆台账登记，不要放入 `issues` 重复建档。
