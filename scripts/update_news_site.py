#!/usr/bin/env python3
"""Fetch tech/AI news and regenerate the static site news pages.

Self-contained for cron: fetch public tech/AI items, turn them into Chinese media-style
cards/articles, render static HTML + RSS, then commit/push when credentials are available.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "articles"
NEWS_SKILL = Path.home() / ".hermes/skills/news-aggregator-skill"
SITE_TITLE = "前沿科技观察"
SITE_URL = "https://xiejunjie.indevs.in"
MAX_ITEMS = 8
KEYWORDS = "AI,LLM,GPT,Claude,Agent,RAG,DeepSeek,robot,automation,model"
CSS_VERSION = 10
HERO_TITLE = '读懂下一代<br>科技趋势<br><span class="grad">从模型到产品现场</span>'


def sh(cmd, cwd=None, timeout=180):
    return subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True, timeout=timeout)


def fetch_with_skill():
    script = NEWS_SKILL / "scripts/fetch_news.py"
    if not script.exists():
        return []
    cmd = f"python3 {script} --source hackernews,github,huggingface --keyword '{KEYWORDS}' --limit 6 --no-save"
    p = sh(cmd, cwd=NEWS_SKILL, timeout=240)
    if p.returncode != 0:
        print("skill fetch failed", p.stderr[-500:], file=sys.stderr)
        return []
    try:
        data = json.loads(p.stdout)
    except Exception:
        m = re.search(r"\[\s*\{.*\}\s*\]", p.stdout, re.S)
        data = json.loads(m.group(0)) if m else []
    return [normalize_item(x) for x in data if isinstance(x, dict)]


def fetch_rss(url, source, limit=5):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urlopen(req, timeout=20).read()
        root = ET.fromstring(raw)
        out = []
        for item in root.findall('.//item')[:limit]:
            title = clean_title(item.findtext('title') or '')
            link = (item.findtext('link') or '').strip()
            desc = re.sub('<[^>]+>', ' ', item.findtext('description') or '')
            pub = (item.findtext('pubDate') or item.findtext('updated') or 'Recent').strip()
            if title and link:
                out.append(normalize_item({'source': source, 'title': title, 'url': link, 'time': pub, 'summary': desc[:180]}))
        return out
    except Exception as e:
        print(f"rss failed {url}: {e}", file=sys.stderr)
        return []


def normalize_item(x):
    title = clean_title(x.get('title') or 'Untitled')
    url = str(x.get('url') or x.get('link') or '').strip()
    source = str(x.get('source') or 'Web').strip()
    time_s = str(x.get('time') or x.get('published') or 'Recent').strip()
    heat = str(x.get('heat') or '').strip()
    summary = str(x.get('summary') or '').strip()
    hn_url = str(x.get('hn_url') or '').strip()
    return {'title': title, 'url': url, 'source': source, 'time': time_s, 'heat': heat, 'summary': summary, 'hn_url': hn_url}


def clean_title(title):
    return re.sub(r'\s+', ' ', str(title or '')).strip(' -—|')


def categorize(title, source=''):
    t = (title + ' ' + source).lower()
    rules = [
        (('jailbreak', 'claude', 'safety', 'security', 'oversight', 'policy'), '模型安全'),
        (('ualink', 'accelerator', 'gpu', 'chip', 'nvidia', 'semiconductor', 'server'), 'AI 基础设施'),
        (('agent', 'coding', 'developer', 'github', 'open source', 'cursor', 'code'), '开发者工具'),
        (('pin', 'gadget', 'android', 'iphone', 'hardware', 'robot', 'device'), '智能硬件'),
        (('coinbase', 'workforce', 'market', 'funding', 'vc', 'startup'), '产业观察'),
        (('paper', 'model', 'llm', 'hugging face', 'benchmark', 'dataset'), '模型研究'),
    ]
    for keys, label in rules:
        if any(k in t for k in keys):
            return label
    return '科技趋势'


def zh_title(title):
    t = clean_title(title)
    if re.search(r'[\u4e00-\u9fff]', t):
        return t
    patterns = [
        (r'UALink AI Accelerator Spec Maintains Rapid Update Pace', 'UALink 加速器互联规范持续快节奏更新'),
        (r'Dreamer: Make any coding agent self-evolving, across the whole team', 'Dreamer 让团队里的 Coding Agent 持续自我进化'),
        (r'Humane AI Pin hacks turns the gadget into a standalone Android-powered gadget', 'Humane AI Pin 被改造成独立安卓设备'),
        (r'Flattery jailbreaks Claude into giving bomb-making instructions', '研究发现“奉承式提示”可诱导 Claude 越过安全边界'),
        (r"Trump.*AI Oversight Plan", '美国 AI 监管路线再度引发创投圈争议'),
        (r'Coinbase Cuts 14% of Global Workforce.*AI', 'Coinbase 以 AI 与市场压力为由削减全球团队'),
    ]
    for pat, zh in patterns:
        if re.search(pat, t, re.I):
            return zh
    prefix = categorize(t)
    if prefix == 'AI 基础设施':
        return 'AI 基础设施新动态：' + t
    if prefix == '开发者工具':
        return '开发者工具新趋势：' + t
    if prefix == '智能硬件':
        return '智能硬件观察：' + t
    if prefix == '模型安全':
        return '模型安全警报：' + t
    return '科技前沿：' + t


def make_summary(item):
    raw = clean_title(item.get('title'))
    shown = zh_title(raw)
    src = item.get('source', '')
    cat = categorize(raw, src)
    lower = raw.lower()
    specific = [
        ('ualink', 'UALink 规范的持续更新，说明 AI 加速器之间的高速互联正在从厂商自建能力走向更开放的标准化竞争。它值得关注，因为未来大模型训练和推理集群的成本、可扩展性与供应链选择，都可能被这类互联标准改写。'),
        ('dreamer:', 'Dreamer 试图让 Coding Agent 在团队工作流中不断吸收反馈、自我改进，方向不只是“写代码”，而是让 AI 工具进入协作、复盘和长期演进环节。它代表开发者工具从单次生成走向持续型智能助手。'),
        ('humane ai pin', 'Humane AI Pin 被社区改造成独立安卓设备，显示失败硬件仍可能通过破解和二次开发获得新生命。这类案例值得观察，因为它揭示了 AI 硬件的真正价值可能不在原始商业模式，而在开放性和可改造空间。'),
        ('flattery jailbreaks', '这项讨论指向大模型安全中的一个现实问题：看似温和的社交式话术，也可能绕过模型拒答边界。它提醒厂商不能只防御明显恶意提示，还要处理更隐蔽的心理诱导和上下文操控。'),
        ('coinbase cuts', 'Coinbase 将裁员与 AI、市场周期联系起来，反映出科技公司正在用自动化重新审视组织规模。它不只是单家公司调整，也代表 AI 对岗位结构、运营效率和管理叙事的持续影响。'),
        ('ai oversight', '美国 AI 监管路线的变化再次牵动创业公司、投资机构与模型厂商之间的利益平衡。值得关注的是，监管并非只影响合规成本，也会决定哪些公司能更快把模型能力推向市场。'),
    ]
    for key, text in specific:
        if key in lower:
            return html.escape(text)
    if cat == '开发者工具':
        return html.escape(f'{shown} 正在反映开发者工具链的新变化：AI 不再只承担问答或补全，而是进入编码、测试、协作和自动化交付环节。后续要看它能否真正提升团队效率，而不是制造新的工作流噪音。')
    if cat == 'AI 基础设施':
        return html.escape(f'{shown} 代表 AI 基础设施继续向高性能、标准化和规模化方向推进。对产业来说，关键在于它是否能降低训练/推理成本，并改善多厂商硬件生态的兼容性。')
    if cat == '智能硬件':
        return html.escape(f'{shown} 说明智能硬件仍在探索 AI 能力与真实使用场景之间的平衡。值得观察的是，它能否从概念产品走向稳定、可维护、用户愿意长期使用的设备体验。')
    if cat == '模型安全':
        return html.escape(f'{shown} 暴露出模型安全与可控性仍是大模型商业化的核心变量。安全边界、提示注入和误用防护，会直接影响企业是否敢把模型接入真实业务。')
    return html.escape(f'{shown} 是近期科技社区关注的一个信号。我们更关心它背后的产品方向、生态变化和普通用户可能感受到的体验升级，而不只是单条新闻本身。')


def slugify(title, i):
    s = title.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:54]
    if not s:
        s = f'news-{i}'
    return f"{datetime.now():%Y%m%d}-{s}"


def render_header(active=''):
    def cls(name): return ' class="active"' if active == name else ''
    return f'''<header class="nav"><div class="wrap navin"><a class="brand" href="/"><span class="logo"></span><span>{SITE_TITLE}</span></a><nav class="links"><a{cls('news')} href="/news.html">资讯</a><a href="/projects.html">专题</a><a href="/about.html">关于</a><a href="/contact.html" class="hide-sm">联系</a><a class="btn" href="/rss.xml">RSS</a></nav></div></header>'''


def html_doc(title, body):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · {SITE_TITLE}</title><link rel="stylesheet" href="/styles.css?v={CSS_VERSION}"><link rel="alternate" type="application/rss+xml" title="{SITE_TITLE} RSS" href="/rss.xml"></head><body>{body}</body></html>'''


def render_article(item, slug, idx):
    title = zh_title(item['title'])
    original = clean_title(item['title'])
    src = html.escape(item['source'])
    category = categorize(original, item.get('source', ''))
    summary = make_summary(item)
    source_url = html.escape(item['url'] or item.get('hn_url') or '#')
    discussion = html.escape(item.get('hn_url') or item['url'] or '#')
    body = f'''{render_header('news')}<main class="wrap page article-page"><article class="story"><span class="tag {'hot' if idx == 0 else ''}">{html.escape(category)}</span><h1>{html.escape(title)}</h1><p class="lead">{summary}</p><h2>为什么值得关注</h2><p>这条动态来自公开信息源。我们关注的不只是标题本身，而是它可能如何影响 AI 产品、开发者工具、硬件生态、企业效率和普通用户体验。</p><h2>编辑观察</h2><p>短期看，它更像一个趋势信号；长期看，需要继续验证真实采用率、商业模式、开源生态、监管环境与用户反馈。只有这些因素同时成立，技术热度才可能转化为稳定价值。</p><h2>来源信息</h2><p>来源：{src}。时间：{html.escape(item.get('time') or 'Recent')}。原文标题：{html.escape(original)}。热度：{html.escape(item.get('heat') or '—')}。</p></article><aside class="source-card"><span class="tag">来源入口</span><h3>公开来源</h3><p>点击下方按钮打开原始来源或社区讨论页面。站内内容为中文整理与观察，不替代原文。</p><div class="actions"><a class="btn" href="{source_url}" target="_blank" rel="noopener">打开来源</a><a class="btn secondary" href="{discussion}" target="_blank" rel="noopener">相关讨论</a></div></aside></main>'''
    path = ARTICLES / f"{slug}.html"
    path.write_text(html_doc(title, body), encoding='utf-8')
    return {'title': title, 'original_title': original, 'slug': slug, 'summary': re.sub('<[^>]+>', '', summary), 'source': item['source'], 'category': category, 'url': item['url'], 'time': item['time'], 'heat': item['heat']}


def render_news(items):
    # Keep the hand-designed editorial layout, but refresh only its marked
    # latest-news slot so new articles are visible without replacing the page.
    path = ROOT / 'news.html'
    if not path.exists():
        return
    source = path.read_text(encoding='utf-8')
    start = '<!-- AUTO-NEWS-START -->'
    end = '<!-- AUTO-NEWS-END -->'
    if start not in source or end not in source:
        return
    cards = []
    for i, it in enumerate(items):
        tagcls = 'hot' if i == 0 else ('green' if it['category'] in ('开发者工具', '模型研究') else '')
        cards.append(f'''<a class="article" href="/articles/{it['slug']}.html"><div class="date">{html.escape(it['time'][:18] or '近期')}<br>自动更新 {i + 1:02d}</div><div><span class="tag {tagcls}">{html.escape(it['category'])}</span><h3>{html.escape(it['title'])}</h3><p>{html.escape(it['summary'])}</p><div class="meta"><span>{html.escape(it['source'])}</span><span>约 3 分钟</span><span>最新信号</span></div><span class="link-more">阅读全文 →</span></div></a>''')
    section = f'''{start}
    <section class="section auto-news" aria-label="自动更新内容">
      <div class="section-head editorial-head"><div><span class="eyebrow">LATEST SIGNALS</span><h2>最新更新</h2></div><p>自动抓取并整理的最新科技信号，保留原始来源入口。</p></div>
      <div class="news-list auto-news-list">{''.join(cards)}</div>
    </section>
    {end}'''
    path.write_text(source.replace(source[source.index(start):source.index(end) + len(end)], section), encoding='utf-8')
    return
    cards = []
    for i, it in enumerate(items):
        tagcls = 'hot' if i == 0 else ('green' if it['category'] in ('开发者工具', '模型研究') else '')
        cards.append(f'''<a class="article" href="/articles/{it['slug']}.html"><div class="date">{html.escape(it['time'][:18] or '近期')}</div><div><span class="tag {tagcls}">{html.escape(it['category'])}</span><h3>{html.escape(it['title'])}</h3><p>{html.escape(it['summary'])}</p><div class="meta"><span>{html.escape(it['source'])}</span><span>约 3 分钟</span><span>{html.escape(it['heat'] or '更新')}</span></div><span class="link-more">阅读全文 →</span></div></a>''')
    columns = ''.join(f'''<article class="column-card"><h3>{name}</h3><p>{desc}</p></article>''' for name, desc in [
        ('AI 产品动态', '追踪模型、Agent、自动化工具从发布到落地的真实进展。'),
        ('数码与硬件', '关注智能硬件、机器人、手机电脑和 AI 设备的新体验。'),
        ('开发者生态', '记录开源项目、基础设施、编码工具和技术社区讨论。'),
    ])
    body = f'''{render_header('news')}<main class="wrap page"><div class="eyebrow">Auto-updated News</div><h1 class="page-title">科技 AI 资讯</h1><p class="lead">自动抓取公开来源，并生成中文标题、摘要、详情页和 RSS。每条内容均保留原始来源入口，方便追溯。</p><section class="columns section">{columns}</section><section class="section news-layout"><div class="news-list">{''.join(cards)}</div><aside class="sidebar"><div class="rss-box"><span class="tag hot">自动更新</span><h3>RSS Feed</h3><p>最近更新：{datetime.now():%Y-%m-%d %H:%M}</p><div class="actions"><a class="btn" href="/rss.xml">订阅 RSS</a></div></div><div class="card"><h3>内容来源</h3><p>聚合 Hacker News、GitHub Trending、Hugging Face Papers 与公开 RSS，再进行中文整理。</p></div></aside></section></main><footer class="wrap footer"><div class="footer-row"><span>© 2026 {SITE_TITLE}</span><span>AI · Digital · Automation</span></div></footer>'''
    (ROOT / 'news.html').write_text(html_doc('资讯', body), encoding='utf-8')


def render_index(items):
    top = items[0]
    latest = ''.join(f'''<a class="card" href="/articles/{it['slug']}.html"><div class="time">{html.escape(it['category'])} · {html.escape(it['source'])}</div><h3>{html.escape(it['title'])}</h3><p>{html.escape(it['summary'])}</p><span class="link-more">阅读全文 →</span></a>''' for it in items[:4])
    ticker = ''.join(f'<span>{html.escape(it["category"])}：{html.escape(it["title"])}</span>' for it in items[:4])
    body = f'''{render_header()}<main><section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">Independent Tech Intelligence</div><h1>{HERO_TITLE}</h1><p class="lead">追踪 AI、数码、智能硬件和自动化工具的重要变化，用中文标题、重点摘要和来源追溯，整理成更像媒体而不是标题聚合的科技首页。</p><div class="actions"><a class="btn" href="/news.html">进入资讯页</a><a class="btn secondary" href="/articles/{top['slug']}.html">阅读头条</a></div></div><aside class="hero-board"><div class="board-top"><span>TODAY'S LEAD</span><span>{html.escape(top['source'])}</span></div><a class="headline-card" href="/articles/{top['slug']}.html"><div><span class="tag hot">{html.escape(top['category'])}</span><h2>{html.escape(top['title'])}</h2><p>{html.escape(top['summary'])}</p></div><span class="link-more">阅读全文 →</span></a><div class="mini-grid">{''.join(f'<a class="mini" href="/articles/{it["slug"]}.html"><b>{html.escape(it["category"][:12])}</b><span>{html.escape(it["title"])}</span></a>' for it in items[1:3])}</div></aside></div></section><div class="ticker"><div class="wrap"><b>今日观察</b>{ticker}</div></div><section class="wrap section"><div class="section-head"><h2>最新内容</h2><p>标题经过中文化处理，摘要补充“为什么重要”，并保留原始来源入口，降低自动聚合站的空洞感。</p></div><div class="latest">{latest}</div></section></main><footer class="wrap footer"><div class="footer-row"><span>© 2026 {SITE_TITLE}</span><span>AI · Digital · Automation</span></div></footer>'''
    (ROOT / 'index.html').write_text(html_doc('AI 与数码资讯', body), encoding='utf-8')


def render_rss(items):
    now = format_datetime(datetime.now(timezone.utc))
    entries = []
    for it in items:
        link = f"{SITE_URL}/articles/{it['slug']}.html"
        entries.append(f'''<item><title>{html.escape(it['title'])}</title><link>{link}</link><guid>{link}</guid><pubDate>{now}</pubDate><description>{html.escape(it['summary'])}</description></item>''')
    rss = f'''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{SITE_TITLE}</title><link>{SITE_URL}/</link><description>AI、数码、智能硬件与自动化工具资讯。</description><language>zh-CN</language><lastBuildDate>{now}</lastBuildDate>{''.join(entries)}</channel></rss>'''
    (ROOT / 'rss.xml').write_text(rss, encoding='utf-8')
    (ROOT / 'feed.xml').write_text(rss, encoding='utf-8')


def main():
    ARTICLES.mkdir(exist_ok=True)
    raw = fetch_with_skill()
    raw += fetch_rss('https://hnrss.org/newest?q=AI', 'Hacker News RSS', 4)
    seen = set(); unique = []
    for x in raw:
        key = (x['title'].lower(), x['url'])
        if x['title'] and key not in seen:
            seen.add(key); unique.append(x)
    if not unique:
        raise SystemExit('no news fetched')
    selected = unique[:MAX_ITEMS]
    rendered = []
    for i, item in enumerate(selected):
        slug = slugify(item['title'], i)
        rendered.append(render_article(item, slug, i))
    render_news(rendered)
    render_index(rendered)
    render_rss(rendered)
    print(f"updated {len(rendered)} items at {datetime.now():%F %T}")
    if (ROOT / '.git').exists():
        sh('git add index.html news.html rss.xml feed.xml articles/*.html scripts/update_news_site.py styles.css contact.html about.html api.html projects.html', cwd=ROOT)
        diff = sh('git diff --cached --quiet', cwd=ROOT)
        if diff.returncode != 0:
            sh(f'git commit -m "feat: improve tech media site polish {datetime.now():%Y-%m-%d}"', cwd=ROOT)
        push = sh('git push origin main', cwd=ROOT, timeout=120)
        if push.returncode != 0:
            print('git push skipped/failed:', push.stderr.strip()[-300:], file=sys.stderr)
        token = os.environ.get('CLOUDFLARE_API_TOKEN')
        account = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
        if token and account:
            deploy = sh('CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$CLOUDFLARE_ACCOUNT_ID" npx wrangler pages deploy . --project-name xiejunjie-site --branch main --commit-dirty=true', cwd=ROOT, timeout=300)
            if deploy.returncode != 0:
                print('cloudflare pages deploy skipped/failed:', deploy.stderr.strip()[-500:], file=sys.stderr)


if __name__ == '__main__':
    main()
