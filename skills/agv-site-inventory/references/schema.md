# 输出结构

```json
{
  "draft": {
    "inventory_items": [
      {
        "item_code": "TOOL-001",
        "name": "激光测距仪",
        "category": "tool",
        "ownership": "company",
        "tracking_mode": "serial",
        "specification": "0.05-80m",
        "serial_number": "SN123",
        "quantity": 1,
        "minimum_quantity": null,
        "unit": "台",
        "status": "on_site",
        "location": "现场工具柜 A",
        "custodian": "张工",
        "supplier": "",
        "received_date": "2026-08-14",
        "expected_return_date": null,
        "note": "",
        "extra": {}
      }
    ]
  },
  "missing_fields": [],
  "conflicts": [],
  "assumptions": [],
  "change_summary": []
}
```

- `category`: `equipment/tool/spare_part/material/consumable/document/other`
- `ownership`: `company/client/third_party`
- `tracking_mode`: `quantity/serial`
- `status`: `expected/in_transit/on_site/in_use/loaned/consumed/returned/lost/damaged/scrapped`
- 日期必须为 `YYYY-MM-DD` 或 `null`；数量不得为负数。
