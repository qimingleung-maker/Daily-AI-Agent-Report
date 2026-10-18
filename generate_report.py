#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日「AI × Agent 创业机会」报告生成器
- 云端：由 GitHub Actions 每天 07:00（北京时间）定时调用
- 本机：也可手动运行  python generate_report.py --dry-run  测试
依赖：Python 标准库（无第三方包），需环境变量 DEEPSEEK_API_KEY
流程：DeepSeek 搜索 API 抓真实市场信号 -> DeepSeek 模型归纳为结构化 JSON -> 套模板出 HTML
"""
import os, sys, json, re, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(ROOT, "模板", "report-template.html")
OUT_DIR = os.path.join(ROOT, "每日报告")
INDEX_PATH = os.path.join(ROOT, "index.html")

API_URL = "https://api.deepseek.com/chat/completions"
SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
# deepseek-flash 便宜够用；追求更高分析质量可改成 deepseek-v4-pro（约 3.4 倍价）
MODEL = "deepseek-flash"

# 每日搜索方向：用 DeepSeek 官方搜索 API 抓真实市场信号（¥5/千次）
SEARCH_QUERIES = [
    "AI 数字人 无人直播 电商 提效 需求 lang:zh",
    "电商 AI Agent 自动化 无人化 市场机会 lang:zh",
    "制造业 传统行业 AI 智能体 落地 需求 lang:zh",
    "企业 AI Agent 自动化 改造 机会 案例 lang:zh",
]

# 免费 RSS 仅作为搜索失败时的兜底（尽力而为）
RSS_FEEDS = [
    "https://36kr.com/feed",
    "https://www.jiqizhixin.com/rss",
    "https://www.qbitai.com/feed",
    "https://www.ithome.com/rss/",
]

def now_cn():
    """当前北京时间（UTC+8）"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))

def http_post_json(url, payload, api_key, timeout):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def search(api_key, query, count=6, need_content=False):
    """调用 DeepSeek 搜索 API，返回 results 列表"""
    resp = http_post_json(SEARCH_URL, {
        "query": query, "count": count, "need_content": need_content,
    }, api_key, 30)
    return resp.get("results") or []

def fetch_rss_headlines():
    headlines = []
    for url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read().decode("utf-8", errors="ignore")
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", data)
            for t in titles[:10]:
                t = re.sub(r"\s+", " ", t).strip()
                if t and len(t) > 5:
                    headlines.append(t)
        except Exception as e:
            print(f"[rss] 跳过 {url}: {e}")
    seen, out = set(), []
    for h in headlines:
        if h not in seen:
            seen.add(h); out.append(h)
    return out[:40]

def gather_signals(api_key):
    """优先用 DeepSeek 搜索 API 抓真实市场信号；全失败则回退 RSS"""
    lines = []
    if api_key:
        for q in SEARCH_QUERIES:
            try:
                for r in search(api_key, q, count=6):
                    title = (r.get("title") or "").strip()
                    site = r.get("site_name") or ""
                    date = (r.get("date") or "")[:10]
                    summ = (r.get("summary") or r.get("snippet") or "").strip()
                    if title:
                        line = f"- [{date}] {title}（{site}）：{summ}"
                        lines.append(line)
            except Exception as e:
                print(f"[search] 跳过 {q}: {e}")
    seen, out = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l); out.append(l)
    if out:
        return "\n".join(out[:60])
    hd = fetch_rss_headlines()
    if hd:
        return "\n".join(f"- {h}" for h in hd)
    return "（未获取到信号，请检查 Key 余额或网络）"

def build_prompt(date_str, signals_text):
    return f"""今天是 {date_str}（北京时间）。下面是通过 DeepSeek 搜索获取的近期市场信号（含标题/来源/日期/摘要，仅作参考）：

{signals_text}

请以「资深 AI 创业机会研究员」身份，产出一份可落地的创业机会清单，**只输出一个合法 JSON 对象**，不要输出任何解释、markdown 代码块或多余文字。JSON 结构必须如下：

{{
  "title": "一句话标题（≤20字，含社媒电商AI与Agent等关键词）",
  "slug": "文件名概要（≤12个中文字，不含空格/标点，如：社媒电商AI与Agent机会）",
  "subtitle": "报告副标题，说明覆盖两大方向",
  "opportunities": [
    {{
      "domain": "social 或 industry（social=社媒电商AI提效/自动化/无人化；industry=传统行业AI+智能体+自动化改造）",
      "title": "机会名称（≤18字）",
      "summary": "一句话机会描述（含关键数据或趋势）",
      "priority": "高/中/低",
      "difficulty": "易/中/难（1~2人落地难度）",
      "market": "市场规模或赛道（≤12字）",
      "pain": "真实痛点/需求（1~2句）",
      "signal": "需求信号，尽量引用上面搜索到的信息并注明来源/日期",
      "customer": "目标客户群体",
      "product": "产品形态",
      "monetize": "变现路径",
      "revenue": "收入模型/客单价",
      "coldstart": "冷启动步骤（3步）",
      "benchmark": "对标案例/工具",
      "risk": "风险与注意事项"
    }}
  ]
}}

硬性要求：
1. opportunities 共 6~8 条，social 与 industry 各 3~4 条。
2. 每条必须真实可落地、面向 1~2 人小团队、目标是年利润 100~200 万元人民币。
3. 优先基于上面搜索到的真实信号（政策、融资/招聘、新闻案例、供应链痛点、高频重复劳动），避免空泛概念。
4. "signal" 字段给出具体来源/日期；引用搜索条目时保留其核心信息。
5. domain 只能取 "social" 或 "industry"；priority 只能取 高/中/低；difficulty 只能取 易/中/难。"""

SYSTEM_PROMPT = ("你是资深 AI 创业机会研究员与商业分析师，擅长发现「社媒电商 AI 提效/自动化/无人化」"
                 "与「传统行业 AI+智能体+自动化改造」的真实市场需求，并给出 1~2 人可落地、可变现的商业机会。")

def call_deepseek(api_key, prompt):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    last_err = None
    for attempt in range(1, 4):
        try:
            body = http_post_json(API_URL, payload, api_key, 180)
            content = (body["choices"][0]["message"]["content"] or "").strip()
            if content:
                return content
            print(f"[api] 第 {attempt} 次返回空 content，重试…")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:500]
            print(f"[api] HTTP {e.code}: {detail}")
            raise  # 401/402 等不可重试，直接抛出
        except Exception as e:
            last_err = e
            print(f"[api] 第 {attempt} 次异常: {e}")
    raise RuntimeError("DeepSeek 多次返回空 content，请检查 prompt 或稍后重试") from last_err

def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型未返回 JSON")
    return json.loads(text[start:end + 1])

def sanitize_slug(s):
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s or "")
    return s[:20] or "AI与Agent机会"

def make_placeholder_report(date_str, signals_text):
    """--dry-run 用占位示例"""
    first = (signals_text.splitlines() or [""])[0] if signals_text else ""
    sig = first if first and first != "（未获取到信号，请检查 Key 余额或网络）" else "（未获取到信号，请在配置 API Key 后重跑）"
    return {
        "title": "社媒电商 AI 与 Agent 市场机会",
        "slug": "社媒电商AI与Agent机会",
        "subtitle": "占位示例：正式报告需配置 DEEPSEEK_API_KEY 后由云端自动生成。",
        "date": date_str,
        "opportunities": [
            {
                "domain": "social", "title": "数字人直播代播 / 无人直播矩阵",
                "summary": "AI 数字人 7×24 无人直播替代真人主播，需求被平台侧验证。",
                "priority": "高", "difficulty": "易", "market": "电商直播",
                "pain": "真人主播贵、时长受限，中小商家无力持续开播。",
                "signal": sig,
                "customer": "中小电商卖家、产业带工厂自播、本地生活商家。",
                "product": "数字人直播 SaaS / 代播服务。",
                "monetize": "代播费 + SaaS 订阅 + 佣金。",
                "revenue": "代播 3000~2 万/月/账号。",
                "coldstart": "① 选垂直品类打样 ② 跑通话术模板 ③ 签种子客户验证。",
                "benchmark": "Heygen、硅基智能、腾讯智影。",
                "risk": "平台无人直播规则风险。"
            },
            {
                "domain": "industry", "title": "企业级 Agent：巡检/对账/周报自动化",
                "summary": "把高频重复的巡检报告、对账、周报交给 Agent 自动完成。",
                "priority": "高", "difficulty": "易", "market": "企业服务",
                "pain": "一线员工每天大量时间耗在重复报表与对账上。",
                "signal": sig,
                "customer": "银行/金融、连锁门店、中小企业。",
                "product": "流程 Agent + 知识库问答。",
                "monetize": "按场景交付 + 月订阅。",
                "revenue": "场景 1~5 万；订阅 3000~1 万/月。",
                "coldstart": "① 选低风险场景 ② RPA+LLM 做 MVP ③ 用节省工时量化说服客户。",
                "benchmark": "RPA+LLM 办公自动化。",
                "risk": "数据权限与合规。"
            }
        ]
    }

def render_and_write(report):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    report_json = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    rendered = re.sub(
        r"const REPORT = \{.*?\};",
        lambda m: "const REPORT = " + report_json + ";",
        template, count=1, flags=re.DOTALL,
    )
    if report_json not in rendered:
        print("ERROR: 模板注入失败，未找到 REPORT 占位"); sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    slug = sanitize_slug(report.get("slug") or report.get("title"))
    filename = f"{report['date']}-{slug}.html"
    out_path = os.path.join(OUT_DIR, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"[ok] 报告 -> {out_path}")
    print(f"[ok] 最新 -> {INDEX_PATH}")

def main():
    dry_run = "--dry-run" in sys.argv
    date_str = now_cn().strftime("%Y-%m-%d")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()

    print(f"[info] 日期={date_str}  模型={MODEL}  模式={'dry-run' if dry_run else 'prod'}")

    if dry_run:
        signals = "（dry-run 占位信号）"
        report = make_placeholder_report(date_str, signals)
    else:
        if not api_key:
            print("ERROR: 未设置环境变量 DEEPSEEK_API_KEY"); sys.exit(1)
        signals = gather_signals(api_key)
        print(f"[signal] 获取到 {len(signals.splitlines())} 条信号")
        prompt = build_prompt(date_str, signals)
        raw = call_deepseek(api_key, prompt)
        report = extract_json(raw)

    # 规范化与兜底
    report["date"] = date_str
    report.setdefault("title", "社媒电商 AI 与 Agent 市场机会")
    report.setdefault("slug", "社媒电商AI与Agent机会")
    report.setdefault("subtitle", "聚焦社媒电商 AI 与 Agent 的真实需求、变现路径与可落地的订单机会。")
    opps = report.get("opportunities") or []
    valid = []
    for o in opps:
        if not isinstance(o, dict):
            continue
        o["domain"] = "social" if o.get("domain") != "industry" else "industry"
        for k in ["title", "summary", "pain", "signal", "customer", "product",
                  "monetize", "revenue", "coldstart", "benchmark", "risk"]:
            o.setdefault(k, "")
        o.setdefault("priority", "中")
        o.setdefault("difficulty", "中")
        o.setdefault("market", "")
        valid.append(o)
    if not valid:
        print("ERROR: 模型未返回有效机会"); sys.exit(1)
    report["opportunities"] = valid

    render_and_write(report)

if __name__ == "__main__":
    main()
