#!/usr/bin/env python3
"""Fetch tech/AI news and regenerate the static site news pages.

This script is intentionally self-contained so cron can run it without chat context.
It uses the installed news-aggregator skill when available, then falls back to RSS/API
sources. Output is static HTML + RSS under /home/xiejunjie/cloudflare-site.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / "articles"
NEWS_SKILL = Path.home() / ".hermes/skills/news-aggregator-skill"
SITE_TITLE = "前沿科技观察"
SITE_URL = "https://xiejunjie.indevs.in"
MAX_ITEMS = 8
KEYWORDS = "AI,LLM,GPT,Claude,Agent,RAG,DeepSeek,robot,automation,model"


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
        req = Request(url, headers={"User-Agent":"Mozilla/5.0"})
        raw = urlopen(req, timeout=20).read()
        root = ET.fromstring(raw)
        out=[]
        for item in root.findall('.//item')[:limit]:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = re.sub('<[^>]+>',' ', item.findtext('description') or '')
            pub = (item.findtext('pubDate') or item.findtext('updated') or 'Recent').strip()
            if title and link:
                out.append(normalize_item({'source':source,'title':title,'url':link,'time':pub,'summary':desc[:180]}))
        return out
    except Exception as e:
        print(f"rss failed {url}: {e}", file=sys.stderr)
        return []


def normalize_item(x):
    title = str(x.get('title') or 'Untitled').strip()
    url = str(x.get('url') or x.get('link') or '').strip()
    source = str(x.get('source') or 'Web').strip()
    time_s = str(x.get('time') or x.get('published') or 'Recent').strip()
    heat = str(x.get('heat') or '').strip()
    summary = str(x.get('summary') or '').strip()
    hn_url = str(x.get('hn_url') or '').strip()
    return {'title': title, 'url': url, 'source': source, 'time': time_s, 'heat': heat, 'summary': summary, 'hn_url': hn_url}


def zh_title(title):
    # Keep proper nouns; add concise Chinese framing for English headlines.
    t = re.sub(r'\s+', ' ', title).strip()
    mappings = [
        ('AI', 'AI'), ('Agent', 'Agent'), ('agents', 'Agent'), ('LLM', '大模型'),
        ('GitHub', 'GitHub'), ('OpenAI', 'OpenAI'), ('model', '模型'), ('robot', '机器人'),
    ]
    if re.search(r'[\u4e00-\u9fff]', t):
        return t[:90]
    if len(t) > 80:
        t = t[:77] + '...'
    return t


def make_summary(item):
    if item.get('summary'):
        return html.escape(item['summary'][:180])
    title = item['title']
    src = item['source']
    if 'github' in src.lower():
        return '这个开源项目受到开发者关注，值得观察它在 AI 工具链、自动化或基础设施中的实际价值。'
    if 'hacker' in src.lower():
        return '这条技术社区讨论反映了开发者对 AI、软件工程或数字产业变化的关注。'
    if 'hugging' in src.lower():
        return '这篇 AI 研究内容值得关注其方法、数据、评测和潜在应用场景。'
    return '这条科技动态值得继续跟踪其对产品、产业和用户体验的影响。'


def slugify(title, i):
    s = title.lower()
    s = re.sub(r'[^a-z0-9]+','-',s).strip('-')[:54]
    if not s:
        s = f'news-{i}'
    return f"{datetime.now():%Y%m%d}-{s}"


def render_header(active=''):
    def cls(name): return ' class="active"' if active == name else ''
    return f'''<header class="nav"><div class="wrap navin"><a class="brand" href="/"><span class="logo"></span><span>{SITE_TITLE}</span></a><nav class="links"><a{cls('news')} href="/news.html">资讯</a><a href="/projects.html">专题</a><a href="/about.html">关于</a><a href="/contact.html" class="hide-sm">联系</a><a class="btn" href="/rss.xml">RSS</a></nav></div></header>'''


def html_doc(title, body):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · {SITE_TITLE}</title><link rel="stylesheet" href="/styles.css?v=6"><link rel="alternate" type="application/rss+xml" title="{SITE_TITLE} RSS" href="/rss.xml"></head><body>{body}</body></html>'''


def render_article(item, slug, idx):
    title = zh_title(item['title'])
    src = html.escape(item['source'])
    summary = make_summary(item)
    source_url = html.escape(item['url'] or item.get('hn_url') or '#')
    discussion = html.escape(item.get('hn_url') or item['url'] or '#')
    body = f'''{render_header('news')}<main class="wrap page article-page"><article class="story"><span class="tag {'hot' if idx == 0 else ''}">{src}</span><h1>{html.escape(title)}</h1><p class="lead">{summary}</p><h2>为什么值得关注</h2><p>这条动态来自公开信息源，反映了 AI、开发者工具、智能硬件或数字产业中的新变化。我们关注的重点不是单个标题本身，而是它可能如何影响产品方向、技术生态和普通用户体验。</p><h2>观察角度</h2><p>后续可以继续追踪三个问题：它是否能进入真实工作流；是否有足够清晰的商业或开源生态；以及它是否会改变用户对设备、软件或内容生产的使用习惯。</p><h2>来源信息</h2><p>来源：{src}。时间：{html.escape(item.get('time') or 'Recent')}。热度：{html.escape(item.get('heat') or '—')}。</p></article><aside class="source-card"><span class="tag">来源入口</span><h3>公开来源</h3><p>点击下方按钮打开原始来源或社区讨论页面。</p><div class="actions"><a class="btn" href="{source_url}" target="_blank" rel="noopener">打开来源</a><a class="btn secondary" href="{discussion}" target="_blank" rel="noopener">相关讨论</a></div></aside></main>'''
    path = ARTICLES / f"{slug}.html"
    path.write_text(html_doc(title, body), encoding='utf-8')
    return {'title': title, 'slug': slug, 'summary': re.sub('<[^>]+>','',summary), 'source': item['source'], 'url': item['url'], 'time': item['time'], 'heat': item['heat']}


def render_news(items):
    cards=[]
    for i,it in enumerate(items):
        tagcls = 'hot' if i == 0 else ('green' if 'GitHub' in it['source'] else '')
        cards.append(f'''<a class="article" href="/articles/{it['slug']}.html"><div class="date">{html.escape(it['time'][:18] or '近期')}</div><div><span class="tag {tagcls}">{html.escape(it['source'])}</span><h3>{html.escape(it['title'])}</h3><p>{html.escape(it['summary'][:150])}</p><div class="meta"><span>AI</span><span>Tech</span><span>{html.escape(it['heat'] or 'Update')}</span></div><span class="link-more">阅读全文 →</span></div></a>''')
    body = f'''{render_header('news')}<main class="wrap page"><div class="eyebrow">Auto-updated News</div><h1 class="page-title">科技 AI 资讯</h1><p class="lead">自动抓取公开来源，生成站内摘要、详情页和 RSS。每条内容均可进入详情页，并提供原始来源跳转。</p><section class="section news-layout"><div class="news-list">{''.join(cards)}</div><aside class="sidebar"><div class="rss-box"><span class="tag hot">自动更新</span><h3>RSS Feed</h3><p>最近更新：{datetime.now():%Y-%m-%d %H:%M}</p><div class="actions"><a class="btn" href="/rss.xml">订阅 RSS</a></div></div><div class="card"><h3>来源</h3><p>Hacker News、GitHub Trending、Hugging Face Papers 与公开 RSS。</p></div></aside></section></main><footer class="wrap footer"><div class="footer-row"><span>© 2026 {SITE_TITLE}</span><span>Auto-updated</span></div></footer>'''
    (ROOT/'news.html').write_text(html_doc('资讯', body), encoding='utf-8')


def render_index(items):
    top = items[0]
    latest = ''.join(f'''<a class="card" href="/articles/{it['slug']}.html"><div class="time">{html.escape(it['source'])}</div><h3>{html.escape(it['title'][:36])}</h3><p>{html.escape(it['summary'][:76])}</p><span class="link-more">阅读全文 →</span></a>''' for it in items[:4])
    ticker = ''.join(f'<span>{html.escape(it["title"][:26])}</span>' for it in items[:4])
    body = f'''{render_header()}<main><section class="hero"><div class="wrap hero-grid"><div><div class="eyebrow">Independent Tech Intelligence</div><h1>读懂下一代科技趋势<br><span class="grad">从模型到产品现场</span></h1><p class="lead">自动追踪 AI、数码、智能硬件和自动化工具的重要变化，生成可阅读、可订阅、可追溯来源的科技媒体首页。</p><div class="actions"><a class="btn" href="/news.html">进入资讯页</a><a class="btn secondary" href="/articles/{top['slug']}.html">阅读头条</a></div></div><aside class="hero-board"><div class="board-top"><span>TODAY'S LEAD</span><span>{html.escape(top['source'])}</span></div><a class="headline-card" href="/articles/{top['slug']}.html"><div><span class="tag hot">今日头条</span><h2>{html.escape(top['title'])}</h2><p>{html.escape(top['summary'][:130])}</p></div><span class="link-more">阅读全文 →</span></a><div class="mini-grid">{''.join(f'<a class="mini" href="/articles/{it["slug"]}.html"><b>{html.escape(it["source"][:12])}</b><span>{html.escape(it["title"][:24])}</span></a>' for it in items[1:3])}</div></aside></div></section><div class="ticker"><div class="wrap"><b>今日观察</b>{ticker}</div></div><section class="wrap section"><div class="section-head"><h2>最新内容</h2><p>自动生成站内详情页，并保留原始来源入口，避免只有标题没有内容。</p></div><div class="latest">{latest}</div></section></main><footer class="wrap footer"><div class="footer-row"><span>© 2026 {SITE_TITLE}</span><span>AI · Digital · Automation</span></div></footer>'''
    (ROOT/'index.html').write_text(html_doc('AI 与数码资讯', body), encoding='utf-8')


def render_rss(items):
    now = format_datetime(datetime.now(timezone.utc))
    entries=[]
    for it in items:
        link=f"{SITE_URL}/articles/{it['slug']}.html"
        entries.append(f'''<item><title>{html.escape(it['title'])}</title><link>{link}</link><guid>{link}</guid><pubDate>{now}</pubDate><description>{html.escape(it['summary'])}</description></item>''')
    rss=f'''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{SITE_TITLE}</title><link>{SITE_URL}/</link><description>AI、数码、智能硬件与自动化工具资讯。</description><language>zh-CN</language><lastBuildDate>{now}</lastBuildDate>{''.join(entries)}</channel></rss>'''
    (ROOT/'rss.xml').write_text(rss, encoding='utf-8')
    (ROOT/'feed.xml').write_text(rss, encoding='utf-8')


def main():
    ARTICLES.mkdir(exist_ok=True)
    raw = fetch_with_skill()
    raw += fetch_rss('https://hnrss.org/newest?q=AI', 'Hacker News RSS', 4)
    seen=set(); unique=[]
    for x in raw:
        key=(x['title'].lower(), x['url'])
        if x['title'] and key not in seen:
            seen.add(key); unique.append(x)
    if not unique:
        raise SystemExit('no news fetched')
    selected=unique[:MAX_ITEMS]
    rendered=[]
    for i,item in enumerate(selected):
        slug=slugify(item['title'], i)
        rendered.append(render_article(item, slug, i))
    render_news(rendered)
    render_index(rendered)
    render_rss(rendered)
    print(f"updated {len(rendered)} items at {datetime.now():%F %T}")
    # Commit if repo has changes. Push only if credentials exist.
    if (ROOT/'.git').exists():
        sh('git add index.html news.html rss.xml feed.xml articles/*.html scripts/update_news_site.py', cwd=ROOT)
        diff=sh('git diff --cached --quiet', cwd=ROOT)
        if diff.returncode != 0:
            sh(f'git commit -m "chore: auto-update news {datetime.now():%Y-%m-%d}"', cwd=ROOT)
        push=sh('git push origin main', cwd=ROOT, timeout=120)
        if push.returncode != 0:
            print('git push skipped/failed:', push.stderr.strip()[-300:], file=sys.stderr)

if __name__ == '__main__':
    main()
