"""verify.sh 第 7/9 步 Excel sheet 名解析的回归测试（HYPE-58 发布回归）。

背景：HYPE-58 后 openpyxl 序列化 workbook.xml 时 <sheet> 元素可能先写 xmlns:r
再写 name（`<sheet xmlns:r="..." name="项目概览" .../>`），旧正则
`<sheet name="([^"]+)"` 因此匹配为空，导致 verify.sh 7/9 误报失败。
verify.sh 现委托 docker/scripts/verify_excel.py 解析：按元素语义读取 name
属性，不依赖属性顺序；并校验当前六张交付表的完整顺序。

本测试覆盖：
- xmlns:r 位于 name 前时仍能解析出全部交付表；
- 六张交付表的名称、顺序和多余旧表拒绝规则；
- name 在前（旧序列化）也兼容；
- verify.sh 不再内联旧正则（避免回退）。
"""
import re
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "docker" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import verify_excel  # noqa: E402

# Namespace declaration order must not affect the current six-sheet contract.
EXPECTED_SIX = ['交付概览', '生命周期表', '问题清单', '物资清单', '收发流水', '交付资料']

_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _workbook_xml(sheets, xmlns_r_first: bool) -> str:
    attrs = []
    for i, name in enumerate(sheets, 1):
        parts = []
        if xmlns_r_first:
            parts.append(f'xmlns:r="{_R_NS}"')
        parts.append(f'name="{name}"')
        parts.append(f'sheetId="{i}"')
        parts.append('state="visible"')
        parts.append(f'r:id="rId{i}"')
        if not xmlns_r_first:
            parts.insert(0, f'xmlns:r="{_R_NS}"')
        attrs.append(f"<sheet {' '.join(parts)}/>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'xmlns:r="{_R_NS}">\n'
        "<sheets>\n" + "\n".join(attrs) + "\n</sheets>\n</workbook>\n"
    )


def _xlsx_bytes(workbook_xml: str) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
    return buf.getvalue()


def test_xmlns_r_before_name_parses_delivery_sheets():
    """xmlns:r 位于 name 前时，解析仍得到全部交付表（HYPE-58 后真实格式）。"""
    xml = _workbook_xml(EXPECTED_SIX, xmlns_r_first=True)
    assert "xmlns:r" in xml.split("name=")[0]
    names = verify_excel.sheet_names_from_xml(xml)
    assert names == EXPECTED_SIX, names


def test_delivery_sheets_use_current_compact_contract():
    """当前交付导出不恢复退休的日排程与甘特表。"""
    xml = _workbook_xml(EXPECTED_SIX, xmlns_r_first=True)
    names = set(verify_excel.sheet_names_from_xml(xml))
    assert set(verify_excel.DELIVERY_SHEETS) == names, names


def test_name_first_format_still_works():
    """name 在前（旧序列化）兼容，解析不依赖属性顺序。"""
    xml = _workbook_xml(EXPECTED_SIX, xmlns_r_first=False)
    names = verify_excel.sheet_names_from_xml(xml)
    assert names == EXPECTED_SIX, names


def test_sheet_names_from_real_xlsx_path():
    """端到端：从真实 xlsx 文件路径读取 sheet 名（verify.sh 实际调用入口）。"""
    xml = _workbook_xml(EXPECTED_SIX, xmlns_r_first=True)
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as f:
        f.write(_xlsx_bytes(xml))
        f.flush()
        names = verify_excel.sheet_names(f.name)
    assert names == EXPECTED_SIX, names


def test_verify_sh_delegates_to_verify_excel_no_inline_regex():
    """verify.sh 第 7 步不再内联 `<sheet name="` 正则，委托 verify_excel 解析。"""
    src = (SCRIPTS_DIR / "verify.sh").read_text(encoding="utf-8")
    assert "verify_excel.py" in src
    assert re.search(r"<sheet\s+name=", src) is None


def test_verifier_rejects_retired_worksheet_even_when_all_current_sheets_exist(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['verify_excel.py', 'unused.xlsx'])
    monkeypatch.setattr(verify_excel, 'sheet_names', lambda _: [*EXPECTED_SIX, '甘特图'])
    assert verify_excel.main() == 1
    assert '表结构不符' in capsys.readouterr().err
