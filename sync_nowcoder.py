#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
牛客网「专栏」笔试合集 同步脚本
================================

功能：抓取牛客网指定专栏里的全部文章（标题 + 链接 + 正文中的笔试时间），
     与本地项目已有的文章做比对，找出「新增」文章，按公司 / 笔试时间归类，
     并自动插入到对应公司的 markdown 文件与 README.md（保持“时间从近到远”的排序）。

用法：
    python3 sync_nowcoder.py                 # 只检测，不修改任何文件（dry-run，默认）
    python3 sync_nowcoder.py --apply         # 检测 + 写入新增文章
    python3 sync_nowcoder.py --check         # 本地校验（完整性 / 排序 / 文件一致性），不联网
    python3 sync_nowcoder.py --columns 0ox5Z3,0ODrNm    # 指定要监控的专栏

依赖：仅 Python3 标准库，无第三方依赖。
参考文档：见同目录《同步指南.md》。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

# ======================================================================
# 配置区
# ======================================================================

# 牛客网主站
BASE_URL = "https://www.nowcoder.com"

# 默认监控的专栏 ID（牛客网「专栏」）。0ox5Z3 = 2025/2026 合集，0ODrNm = 2023 合集。
DEFAULT_COLUMNS = ["0ox5Z3", "0ODrNm"]

# 项目根目录（本脚本所在目录）
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
README_PATH = os.path.join(PROJECT_DIR, "README.md")

# 请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# 抓取文章详情时每次请求之间的间隔（秒），避免请求过快
FETCH_DELAY = 0.3

# ----------------------------------------------------------------------
# 公司分类关键词表。
# 顺序：越靠前越优先匹配。关键词对标题做「忽略大小写的子串」匹配。
# 注意：阿里系（淘天/饿了么/盒马/菜鸟/高德/钉钉/大文娱/通义/达摩院）都归到「阿里」；
#       「灵犀互娱」是独立公司，与阿里的「阿里灵犀」不同，因此单独列在阿里之后仍能被
#       正确区分（因为「灵犀互娱」标题里不含「阿里」，而「阿里灵犀」标题里含「阿里」）。
# ----------------------------------------------------------------------
COMPANY_KEYWORDS = [
    ("字节跳动", ["字节"]),
    ("阿里", ["阿里", "淘天", "饿了么", "盒马", "菜鸟", "高德", "钉钉", "大文娱", "通义", "达摩院"]),
    ("腾讯", ["腾讯"]),
    ("美团", ["美团"]),
    ("拼多多", ["拼多多"]),
    ("蚂蚁金服", ["蚂蚁"]),
    ("百度", ["百度", "度小满"]),
    ("网易", ["网易"]),
    ("华为", ["华为"]),
    ("荣耀", ["荣耀"]),
    ("小米", ["小米"]),
    ("oppo", ["oppo", "OPPO"]),
    ("小红书", ["小红书"]),
    ("bilibili", ["bilibili", "哔哩哔哩", "B站"]),
    ("米哈游", ["米哈游"]),
    ("携程", ["携程"]),
    ("快手", ["快手"]),
    ("大疆", ["大疆"]),
    ("滴滴", ["滴滴"]),
    ("得物", ["得物"]),
    ("科大讯飞", ["科大讯飞", "非凡计划"]),
    ("shein", ["shein", "SHEIN"]),
    ("招商银行", ["招商银行", "招行"]),
    ("招银网络", ["招银网络"]),
    ("深信服", ["深信服"]),
    ("用友", ["用友"]),
    ("顺丰", ["顺丰"]),
    ("微众银行", ["微众银行"]),
    ("奇安信", ["奇安信"]),
    ("联想", ["联想"]),
    ("58同城", ["58同城", "58 同城"]),
    ("图森未来", ["图森未来"]),
    ("富途", ["富途"]),
    ("去哪儿", ["去哪儿"]),
    ("蔚来", ["蔚来"]),
    ("茄子科技", ["茄子科技"]),
    ("猿辅导", ["猿辅导"]),
    ("中国电信", ["中国电信"]),
    ("京东", ["京东"]),
    ("美的", ["美的"]),
    ("众安保险", ["众安保险", "众安"]),
    ("360", ["360"]),
    ("虾皮", ["虾皮"]),
    ("中国银行", ["中国银行"]),
    ("民生银行", ["民生银行"]),
    ("柠檬微趣", ["柠檬微趣"]),
    ("文远知行", ["文远知行", "文远"]),
    ("灵犀互娱", ["灵犀互娱"]),
    ("vivo", ["vivo"]),
    ("Funplus", ["Funplus", "FunPlus", "趣加"]),
    ("吉比特", ["吉比特"]),
    ("天翼云", ["天翼云"]),
    ("理想汽车", ["理想汽车", "理想"]),
    ("广联达", ["广联达"]),
    ("迅雷", ["迅雷"]),
    ("中兴", ["中兴"]),
    ("同程", ["同程"]),
    ("极兔快递", ["极兔快递", "极兔快速", "极兔"]),
    ("金山", ["金山"]),
    ("恒生电子", ["恒生电子"]),
    ("中国移动", ["中国移动"]),
    ("DeepSeek", ["DeepSeek", "deepseek"]),
]

# ----------------------------------------------------------------------
# 公司 -> 所属 markdown 文件（相对项目根目录）。
# 值为 None 表示该公司只在 README.md 里维护，没有独立的公司文件。
# ----------------------------------------------------------------------
COMPANY_FILE = {
    "字节跳动": "字节笔试/bytedance.md",
    "阿里": "阿里笔试/alibaba.md",
    "腾讯": "腾讯笔试/tencent.md",
    "美团": "美团笔试/meituan.md",
    "拼多多": "拼多多笔试/pdd.md",
    "蚂蚁金服": "蚂蚁金服笔试/mayi.md",
    "百度": "百度笔试/baidu.md",
    "网易": "网易笔试/wangyi.md",
    "华为": "华为笔试/huawei.md",
    "荣耀": "荣耀笔试/rongyao.md",
    "小米": "小米笔试/xiaomi.md",
    "oppo": "oppo笔试/oppo.md",
    "小红书": "小红书笔试/red.md",
    "bilibili": "bilibili笔试/bilibili.md",
    "米哈游": "米哈游笔试/mihayo.md",
    "携程": "携程笔试/xiechen.md",
    "快手": None,
    "大疆": "z其他笔试/other.md",
    "滴滴": "z其他笔试/other.md",
    "得物": "z其他笔试/other.md",
    "科大讯飞": "z其他笔试/other.md",
    "shein": None,
    "招商银行": None,
    "招银网络": None,
    "深信服": "z其他笔试/other.md",
    "用友": "z其他笔试/other.md",
    "顺丰": "z其他笔试/other.md",
    "微众银行": None,
    "奇安信": None,
    "联想": "z其他笔试/other.md",
    "58同城": None,
    "图森未来": None,
    "富途": None,
    "去哪儿": None,
    "蔚来": "z其他笔试/other.md",
    "茄子科技": None,
    "猿辅导": None,
    "中国电信": "z其他笔试/other.md",
    "京东": "z其他笔试/other.md",
    "美的": "z其他笔试/other.md",
    "众安保险": "z其他笔试/other.md",
    "360": "z其他笔试/other.md",
    "虾皮": "z其他笔试/other.md",
    "中国银行": "z其他笔试/other.md",
    "民生银行": "z其他笔试/other.md",
    "柠檬微趣": "z其他笔试/other.md",
    "文远知行": "z其他笔试/other.md",
    "灵犀互娱": "z其他笔试/other.md",
    "vivo": "z其他笔试/other.md",
    "Funplus": "z其他笔试/other.md",
    "吉比特": "z其他笔试/other.md",
    "天翼云": "z其他笔试/other.md",
    "理想汽车": "z其他笔试/other.md",
    "广联达": "z其他笔试/other.md",
    "迅雷": "z其他笔试/other.md",
    "中兴": "z其他笔试/other.md",
    "同程": "z其他笔试/other.md",
    "极兔快递": "z其他笔试/other.md",
    "金山": "z其他笔试/other.md",
    "恒生电子": "z其他笔试/other.md",
    "中国移动": "z其他笔试/other.md",
    "DeepSeek": "z其他笔试/other.md",
}

# 所有公司（用于校验），顺序即 README 中各小节的展示顺序
ALL_COMPANIES = [c for c, _ in COMPANY_KEYWORDS]

# 两篇新文章正文未标注年份，已根据当前 2026 秋招批次人工核对。
DATE_OVERRIDES = {
    "64e607b8dcd64543ab0f15a86f5a7110": (2026, 9, 4),
    "0e7b6525cfc949b5a70fcf2046868944": (2026, 9, 5),
}


# ======================================================================
# 网络请求
# ======================================================================

def fetch_json(url, retries=3):
    """GET 一个 URL 并解析为 JSON，带简单重试。"""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"请求失败 {url}: {last_err}")


def get_catalog(column_id):
    """获取某专栏的文章目录：返回 [{title, uuid}, ...]（保持原文顺序）。"""
    url = f"{BASE_URL}/content/zhuanlan/index/catalog/{column_id}"
    data = fetch_json(url)
    if data.get("code") != 0:
        raise RuntimeError(f"目录接口返回异常: {data}")
    catalog = data.get("data", {}).get("catalog") or []
    return [{"title": c["title"], "uuid": c["uuid"]} for c in catalog]


def get_detail(column_id, uuid):
    """获取某篇文章详情，返回 (title, content_html)。"""
    url = f"{BASE_URL}/content/zhuanlan/index/detail/{column_id}/{uuid}"
    data = fetch_json(url)
    if data.get("code") != 0:
        raise RuntimeError(f"详情接口返回异常: {data}")
    d = data.get("data", {})
    return d.get("title", ""), d.get("content", "")


# ======================================================================
# 公司分类 / 日期解析 / 标题规范化
# ======================================================================

def classify(title):
    """根据标题判断属于哪家公司；无法判断返回 None。"""
    t = title.lower()
    for company, keywords in COMPANY_KEYWORDS:
        for kw in keywords:
            if kw.lower() in t:
                return company
    return None


def parse_date_from_content(content_html):
    """从正文 HTML 中解析「笔试时间」，返回 (year, month, day)，缺失项为 None。

    正文里典型写法：
      - 笔试时间：京东 2026年8月22日 算法方向机考
      - 笔试时间：2026 年 7 月 24 日
    """
    text = re.sub(r"<[^>]+>", " ", content_html or "")
    text = re.sub(r"\s+", " ", text)
    idx = text.find("笔试时间")
    seg = text[idx:idx + 80] if idx != -1 else text

    year = month = day = None
    m = re.search(r"(20\d{2})\s*年", seg)
    if m:
        year = int(m.group(1))
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", seg)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
    return year, month, day


def parse_date_from_title(title):
    """从标题中尽力解析日期，返回 (year, month, day)，缺失项为 None。

    支持形如：20260314、20250824、8月22日、8 月 15 日、7 月 24 日、0314、0923 等。
    """
    year = month = day = None

    # 1) 8 位数字 YYYYMMDD（如 20260314）
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", title)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    # 2) 开头的年份（如 "2023 京东笔试题 ..."）
    m = re.match(r"^\s*(20\d{2})\b", title)
    if m:
        year = int(m.group(1))

    # 3) 中文「X 月 Y 日」（含带空格/不带空格两种）
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", title)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))

    # 4) 4 位数字 MMDD（如 0314、0923），跳过年份（20 开头月份不合法）
    if month is None:
        for m in re.finditer(r"(?<!\d)(\d{2})(\d{2})(?!\d)", title):
            mm, dd = int(m.group(1)), int(m.group(2))
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                month, day = mm, dd
                break

    return year, month, day


def extract_exam_date(content_html, title):
    """综合正文 + 标题得到笔试日期 (year, month, day)，缺失项为 None。"""
    cy, cm, cd = parse_date_from_content(content_html)
    ty, tm, td = parse_date_from_title(title)
    year = cy or ty
    month = cm or tm
    day = cd or td
    return year, month, day


def normalize_title(title):
    """规范化标题：去掉开头的年份、统一「X月Y日 -> X 月 Y 日」、YYYYMMDD -> MMDD。"""
    t = title.strip()
    # 去掉开头的年份前缀，如 "2023 "
    t = re.sub(r"^(20\d{2})\s+", "", t)
    # 8 位 YYYYMMDD 压缩为 MMDD
    t = re.sub(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", r"\2\3", t)
    # 统一中文日期空格
    t = re.sub(r"(\d{1,2})月(\d{1,2})日", r"\1 月 \2 日", t)
    return t.strip()


def make_markdown_line(year, title, column_id, uuid):
    """生成一行 markdown：`[YYYY 标题](链接)`。"""
    return (
        f"[{year} {normalize_title(title)}]"
        f"({BASE_URL}/issue/tutorial?zhuanlanId={column_id}&uuid={uuid})"
    )


def date_key(year, month, day):
    """把日期转成可比较的元组（缺失补 0，用于排序）。"""
    return (year or 0, month or 0, day or 0)


# ======================================================================
# 本地文件读写 / 插入
# ======================================================================

def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def existing_uuids():
    """收集项目里所有 markdown 文件中已收录的文章 uuid。"""
    uuids = set()
    for root, _dirs, files in os.walk(PROJECT_DIR):
        if ".git" in root:
            continue
        for fn in files:
            if fn.endswith(".md"):
                text = read_text(os.path.join(root, fn))
                uuids.update(re.findall(r"uuid=([a-f0-9]{32})", text))
    return uuids


def find_section_bounds(lines, section_name):
    """在 lines 里找到 `### 名称` 小节的 [start, end) 区间；找不到返回 (None, None)。"""
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("### ") and ln[4:].strip() == section_name:
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("### "):
            end = i
            break
    return start, end


def parse_line_date(line):
    """解析一行 markdown 文章 `[YYYY 标题](url)` 的日期，返回 (year, month, day)。"""
    m = re.match(r"\[(\d{4})\s+(.*?)\]\(http", line)
    if not m:
        return None
    year = int(m.group(1))
    _, month, day = parse_date_from_title(m.group(2))
    return year, month, day


def insert_article(lines, section_name, new_line, new_key):
    """把新文章行插入到指定小节中，保持「时间从近到远」。返回新的 lines；小节不存在返回 None。"""
    start, end = find_section_bounds(lines, section_name)
    if start is None:
        return None

    # 找到第一个比新文章更旧的文章行，插在它前面
    insert_at = None
    for i in range(start + 1, end):
        d = parse_line_date(lines[i])
        if d is None:
            continue
        if date_key(*d) < new_key:
            insert_at = i
            break

    if insert_at is not None:
        lines[insert_at:insert_at] = [new_line, ""]
    else:
        # 新文章是最旧的：找到最后一条文章行，插到它后面的空行之后
        last_art = start
        for i in range(start + 1, end):
            if re.match(r"\[\d{4}\s", lines[i]):
                last_art = i
        lines[last_art + 2:last_art + 2] = [new_line, ""]
    return lines


# ======================================================================
# 校验（--check）
# ======================================================================

def check():
    """本地校验 README 完整性 / 排序 / 文件一致性，返回 True 表示全部通过。"""
    print("=" * 60)
    print("开始本地校验（不联网）")
    print("=" * 60)
    ok = True

    readme = read_text(README_PATH)
    readme_lines = readme.split("\n")
    readme_uuids = set(re.findall(r"uuid=([a-f0-9]{32})", readme))

    # 1) 公司文件里的文章是否都在 README 里
    print("\n[1] 公司文件 -> README 一致性")
    missing_in_readme = []
    for company, rel in COMPANY_FILE.items():
        if not rel:
            continue
        path = os.path.join(PROJECT_DIR, rel)
        if not os.path.exists(path):
            print(f"    ⚠️  公司文件不存在：{rel}")
            ok = False
            continue
        uuids = set(re.findall(r"uuid=([a-f0-9]{32})", read_text(path)))
        diff = uuids - readme_uuids
        if diff:
            missing_in_readme.append((company, diff))
    if missing_in_readme:
        for company, diff in missing_in_readme:
            print(f"    ❌ {company} 有 {len(diff)} 篇只在公司文件、README 缺失")
        ok = False
    else:
        print("    ✅ 所有公司文件中的文章都已体现在 README")

    # 2) 各小节年份是否「从近到远」（非递增）
    print("\n[2] README 各小节排序（2026 -> 2025 -> 2023）")
    order_issues = []
    cur = None
    prev_year = None
    for i, ln in enumerate(readme_lines, 1):
        if ln.startswith("### "):
            cur = ln[4:].strip()
            prev_year = None
        elif re.match(r"\[\d{4}\s", ln) and cur:
            y = int(re.match(r"\[(\d{4})\s", ln).group(1))
            if prev_year is not None and y > prev_year:
                order_issues.append((cur, prev_year, y, i))
            prev_year = y
    if order_issues:
        for sec, a, b, i in order_issues:
            print(f"    ❌ {sec} 第 {i} 行：{a} 之后出现更晚的 {b}")
        ok = False
    else:
        print("    ✅ 所有小节年份均为从近到远")

    # 3) 统计
    print("\n[3] 统计")
    section_count = sum(1 for ln in readme_lines if ln.startswith("### "))
    print(f"    README 收录文章：{len(readme_uuids)} 篇")
    print(f"    README 公司小节：{section_count} 个")
    missing_company = [c for c in ALL_COMPANIES if not any(
        ln.startswith("### ") and ln[4:].strip() == c for ln in readme_lines)]
    if missing_company:
        print(f"    ❌ 以下公司在 README 中缺少小节：{missing_company}")
        ok = False
    else:
        print(f"    ✅ {len(ALL_COMPANIES)} 家公司全部有小节")

    print("\n" + ("✅ 校验全部通过" if ok else "❌ 校验发现问题，请人工处理"))
    return ok


# ======================================================================
# 主流程：抓取 + 比对 + 写入
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="牛客网专栏笔试合集同步脚本")
    parser.add_argument("--apply", action="store_true",
                        help="实际写入新增文章（默认只打印，不修改文件）")
    parser.add_argument("--check", action="store_true",
                        help="只做本地校验，不联网抓取")
    parser.add_argument("--columns", type=str, default=",".join(DEFAULT_COLUMNS),
                        help="逗号分隔的专栏 ID，默认 %s" % ",".join(DEFAULT_COLUMNS))
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check() else 1)

    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    mode = "写入" if args.apply else "dry-run（仅检测，不写入）"
    print("=" * 60)
    print(f"牛客网专栏同步  ·  专栏 = {columns}  ·  模式 = {mode}")
    print("=" * 60)

    # 1) 抓取全部目录
    print("\n[1] 抓取专栏目录 ...")
    all_articles = []  # [(column_id, title, uuid)]
    for cid in columns:
        try:
            cat = get_catalog(cid)
            print(f"    {cid}: {len(cat)} 篇")
            all_articles += [(cid, a["title"], a["uuid"]) for a in cat]
        except Exception as e:  # noqa: BLE001
            print(f"    ❌ 抓取 {cid} 失败：{e}")

    # 2) 与本地比对
    print("\n[2] 与本地项目比对 ...")
    existing = existing_uuids()
    print(f"    本地已收录：{len(existing)} 篇")
    new_articles = [a for a in all_articles if a[2] not in existing]
    print(f"    发现新增：{len(new_articles)} 篇")

    if not new_articles:
        print("\n✅ 没有新增文章，项目已是最新。")
        return

    # 3) 逐篇抓取详情，确定笔试时间 + 归类
    print("\n[3] 抓取新增文章详情，确定笔试时间与归类 ...")
    to_add = []  # [(company, year, month, day, markdown_line)]
    problems = []
    for cid, title, uuid in new_articles:
        try:
            _, content = get_detail(cid, uuid)
            time.sleep(FETCH_DELAY)
        except Exception as e:  # noqa: BLE001
            problems.append((title, f"详情抓取失败：{e}"))
            continue

        year, month, day = extract_exam_date(content, title)
        if uuid in DATE_OVERRIDES:
            year, month, day = DATE_OVERRIDES[uuid]
        company = classify(title)
        if year is None:
            problems.append((title, "无法确定笔试年份（正文/标题均无）"))
            continue
        if company is None:
            problems.append((title, "无法归类公司，请在 COMPANY_KEYWORDS 中补充关键词"))
            continue

        line = make_markdown_line(year, title, cid, uuid)
        to_add.append((company, year, month, day, line))
        date_str = f"{year}-{month or '?'}-{day or '?'}"
        print(f"    + [{company}] {date_str}  {title}")

    # 4) 写入（--apply）或打印
    print("\n[4] 处理结果 ...")
    if args.apply:
        # 按 company 分组写入
        written_files = set()
        for company, year, month, day, line in to_add:
            key = date_key(year, month, day)
            targets = [README_PATH]
            rel = COMPANY_FILE.get(company)
            if rel:
                targets.append(os.path.join(PROJECT_DIR, rel))
            for path in targets:
                lines = read_text(path).split("\n")
                new_lines = insert_article(lines, company, line, key)
                if new_lines is None:
                    problems.append((line, f"{path} 中缺少小节「{company}」"))
                    continue
                write_text(path, "\n".join(new_lines))
                written_files.add(path)
                print(f"    写入 {company}: {line[:60]}...")
        print(f"\n    共更新 {len(written_files)} 个文件。")
    else:
        print("    （dry-run）以下文章将被新增：")
        for company, year, month, day, line in to_add:
            print(f"      · [{company}] {line}")

    if problems:
        print("\n⚠️  以下文章需要人工处理：")
        for title, msg in problems:
            print(f"    - {title}\n      {msg}")

    print("\n完成。")


if __name__ == "__main__":
    main()
