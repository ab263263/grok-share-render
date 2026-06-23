# 用户名变体生成器

# leetspeak 字符映射
_LEET_MAP = {
    "a": "4",
    "e": "3",
    "i": "1",
    "o": "0",
    "s": "5",
    "t": "7",
}

# 常见后缀（下划线在开头表示追加到末尾）
_SUFFIXES = ["_official", "_real"]

# 常见前缀（下划线在末尾表示加在开头）
_PREFIXES = ["real_", "the_"]

# 最大返回变体数
_MAX_VARIANTS = 50


def _to_leet(s: str) -> str:
    """将字符串转换为 leetspeak 变体。"""
    return "".join(_LEET_MAP.get(c, c) for c in s.lower())


def _to_camel_case(s: str) -> str:
    """将空格分隔的字符串转为 camelCase。"""
    parts = s.split()
    if not parts:
        return s
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def generate_variants(username: str) -> list[str]:
    """生成用户名变体列表。

    按优先级生成变体，去重后返回（保留原始顺序），最多返回 50 个。

    变体生成规则：
      1. 原始用户名
      2. 小写、大写、首字母大写
      3. 去除空格
      4. 下划线连接
      5. 连字符连接
      6. camelCase
      7. 反转
      8. 首字母变体
      9. leetspeak 变体
      10. 添加常见后缀/前缀
    """
    if not username:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        """添加变体并去重，保留原始顺序。"""
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    # 1. 原始用户名
    add(username)

    # 2. 小写、大写、首字母大写
    add(username.lower())
    add(username.upper())
    add(username.capitalize())

    # 去除空格的版本（用于后续规则的基础）
    no_space = username.replace(" ", "")

    # 3. 去除空格
    add(no_space)

    # 4. 下划线连接
    add(username.replace(" ", "_"))

    # 5. 连字符连接
    add(username.replace(" ", "-"))

    # 6. camelCase
    add(_to_camel_case(username))

    # 7. 反转
    add(no_space[::-1])

    # 8. 首字母变体
    parts = username.split()
    if len(parts) >= 2:
        first = parts[0]
        rest = "".join(parts[1:])
        # j.doe 形式
        add(f"{first[0].lower()}.{rest}")
        # jdoe 形式
        add(f"{first[0].lower()}{rest}")

    # 9. leetspeak 变体
    add(_to_leet(username))
    add(_to_leet(no_space))

    # 10. 添加常见后缀/前缀
    base = no_space.lower()
    for suffix in _SUFFIXES:
        add(f"{base}{suffix}")
    for prefix in _PREFIXES:
        add(f"{prefix}{base}")

    return variants[:_MAX_VARIANTS]
