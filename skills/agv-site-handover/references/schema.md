# 输出结构

输出顶层对象必须包含 `draft`、`missing_fields`、`conflicts`、`assumptions`、`change_summary`。

`draft` 仅包含：

```json
{
  "client_contacts": [
    {
      "department": "",
      "team": "",
      "name": "",
      "title": "",
      "phone": "",
      "email": "",
      "responsibility": "",
      "decision_scope": "",
      "is_primary": false,
      "notes": ""
    }
  ],
  "entry_plan": {
    "mode": "collective|staggered|self_arranged|client_pickup|resident|other|",
    "entry_date": "YYYY-MM-DD 或空字符串",
    "meeting_time": "",
    "meeting_point": "",
    "client_contact": "",
    "contact_phone": "",
    "transport": "",
    "accommodation": "",
    "access_requirements": "",
    "tools_ppe": "",
    "network_access": "",
    "notes": ""
  }
}
```

现有联系人必须保留，除非资料明确要求删除或合并。最多一个 `is_primary=true`。
