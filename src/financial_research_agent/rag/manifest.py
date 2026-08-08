from datetime import date
from pathlib import Path

REPORTS = {
    "maotai_1_诚通证券_2025年年报及2026年一季报点评：顺势出清舒缓压力巩固优势稳健前行.pdf": {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "institution": "诚通证券",
        "report_title": "2025年年报及2026年一季报点评：顺势出清舒缓压力巩固优势稳健前行",
        "report_date": date(2026, 5, 20),
    },
    "maotai_2_华鑫证券_公司事件点评报告：i茅台持续发力，改革效果初显.pdf": {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "institution": "华鑫证券",
        "report_title": "公司事件点评报告：i茅台持续发力，改革效果初显",
        "report_date": date(2026, 5, 2),
    },
    "maotai_3_万联证券_点评报告：业绩稳健增长，直销收入首次超越代理渠道.pdf": {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "institution": "万联证券",
        "report_title": "点评报告：业绩稳健增长，直销收入首次超越代理渠道",
        "report_date": date(2026, 4, 27),
    },
    "ningde_1_交银国际证券_技术发布会简析：技术迭代驱动多维增长，补能生态加速布局.pdf": {
        "stock_code": "300750",
        "stock_name": "宁德时代",
        "institution": "交银国际证券",
        "report_title": "技术发布会简析：技术迭代驱动多维增长，补能生态加速布局",
        "report_date": date(2026, 4, 22),
    },
    "ningde_2_国信证券_产品全面升级，技术创新夯实龙头领先优势.pdf": {
        "stock_code": "300750",
        "stock_name": "宁德时代",
        "institution": "国信证券",
        "report_title": "产品全面升级，技术创新夯实龙头领先优势",
        "report_date": date(2026, 4, 22),
    },
    "ningde_3_国信证券_盈利能力表现稳健，市场份额稳中有升.pdf": {
        "stock_code": "300750",
        "stock_name": "宁德时代",
        "institution": "国信证券",
        "report_title": "盈利能力表现稳健，市场份额稳中有升",
        "report_date": date(2026, 4, 17),
    },
}


def metadata_for(path: Path) -> dict:
    try:
        return REPORTS[path.name]
    except KeyError as exc:
        raise ValueError(f"report is not registered in manifest: {path.name}") from exc
