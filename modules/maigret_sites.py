# Maigret 站点配置加载与管理
import os
import json
from typing import Optional

# 数据文件路径：modules/../data/maigret-sites.json
_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "maigret-sites.json"
)

# 模块级缓存
_sites_cache: Optional[list[dict]] = None


def load_sites() -> list[dict]:
    """从 JSON 文件加载所有站点，返回 list[dict]。

    首次调用后缓存结果，后续调用直接返回缓存。
    """
    global _sites_cache
    if _sites_cache is not None:
        return _sites_cache

    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        _sites_cache = json.load(f)
    return _sites_cache


def get_sites_by_tags(tags: list[str], limit: int = 50) -> list[dict]:
    """按标签筛选站点（tags 交集匹配），按 rank 升序排序。

    只要站点的 tags 与传入 tags 有交集即视为匹配。
    """
    sites = load_sites()
    tag_set = set(tags)
    matched = [s for s in sites if tag_set & set(s.get("tags", []))]
    matched.sort(key=lambda s: s.get("rank", 9999))
    return matched[:limit]


def get_top_sites(limit: int = 50) -> list[dict]:
    """获取 top N 站点（按 rank 升序排序）。"""
    sites = load_sites()
    sorted_sites = sorted(sites, key=lambda s: s.get("rank", 9999))
    return sorted_sites[:limit]


def get_site_by_name(name: str) -> Optional[dict]:
    """按名称获取单个站点，未找到返回 None。"""
    sites = load_sites()
    for s in sites:
        if s.get("name") == name:
            return s
    return None


def search_sites(query: str, limit: int = 20) -> list[dict]:
    """按名称模糊搜索站点（大小写不敏感的子串匹配）。"""
    sites = load_sites()
    q = query.lower()
    matched = [s for s in sites if q in s.get("name", "").lower()]
    return matched[:limit]
