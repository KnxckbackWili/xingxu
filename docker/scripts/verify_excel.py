#!/usr/bin/env python3
"""verify.sh 第 7/9 步的 Excel sheet 名解析：属性顺序无关。

背景（HYPE-58 发布回归）：openpyxl 序列化 workbook.xml 时 <sheet> 元素可能
先写 xmlns:r 再写 name（`<sheet xmlns:r="..." name="项目概览" .../>`），旧正则
`<sheet name="([^"]+)"` 因此匹配为空，verify.sh 7/9 误报失败。
本模块用 xml.etree 按元素语义读取 name 属性，不依赖属性顺序。
"""
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# T27: one compact delivery workbook. Extra retired worksheets are a contract failure.
DELIVERY_SHEETS = ('交付概览', '生命周期表', '问题清单', '物资清单', '收发流水', '交付资料')


def sheet_names_from_xml(xml: str) -> list[str]:
    """从 workbook.xml 文本提取全部 <sheet name="...">，属性顺序无关。"""
    root = ET.fromstring(xml)
    return [el.get("name") for el in root.iter() if el.tag == SHEET_NS + "sheet"]


def sheet_names(xlsx_path: str) -> list[str]:
    """从 xlsx 的 xl/workbook.xml 提取全部 <sheet name="...">，属性顺序无关。"""
    with ZipFile(xlsx_path) as zf:
        xml = zf.read("xl/workbook.xml").decode("utf-8")
    return sheet_names_from_xml(xml)


def main() -> int:
    xlsx = sys.argv[1]
    names = sheet_names(xlsx)
    if names != list(DELIVERY_SHEETS):
        print(f"   ✗ 交付工作簿表结构不符；实际 {names}", file=sys.stderr)
        return 1
    print("   ✓ 交付 Excel:", " / ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
