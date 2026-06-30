"""
GitHub Actions 上运行: 抓 Magnum 街拍专题图文 -> 生成 index.html + post-N.html 到当前目录(仓库根)。
自包含, 仅依赖 requests + pillow。多代理轮询绕 Cloudflare。仅供个人浏览。
"""
import base64, io, json, os, re, time, html, urllib.parse
import requests
from PIL import Image

TAG_RSS = "https://www.magnumphotos.com/tag/street-photography/feed/"
MAX_ITEMS = 10
IMGS_PER = 10
COVER_W = 760
BODY_W = 760
OUTDIR = os.path.dirname(os.path.abspath(__file__))

GLOBAL_DEADLINE = time.time() + 300   # 全脚本最多跑 5 分钟, 到点立即收尾, 绝不卡死
CONN_TIMEOUT = 8                      # 连接超时
READ_TIMEOUT = 15                     # 读取超时(防慢速服务器拖死)


def time_left():
    return GLOBAL_DEADLINE - time.time()


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"


def proxy_urls(t):
    e = urllib.parse.quote(t, safe="")
    return [
        t,                                              # 直连优先(GitHub服务器IP干净, 多半能直接访问 Magnum)
        "https://api.allorigins.win/raw?url=" + e,
        "https://cors.eu.org/" + t,
        "https://api.codetabs.com/v1/proxy/?quest=" + e,
        "https://corsproxy.io/?url=" + e,
    ]


def proxy_get(t, want_image=False, retries=2):
    for _ in range(retries):
        for pu in proxy_urls(t):
            if time_left() < 10:           # 接近总超时, 放弃, 让脚本尽快收尾
                return None
            try:
                r = requests.get(pu, timeout=(CONN_TIMEOUT, READ_TIMEOUT),
                                  headers={"User-Agent": UA})
                ct = r.headers.get("content-type", "")
                if r.status_code == 200:
                    if want_image and "image" in ct and len(r.content) > 3000:
                        return r
                    if (not want_image) and len(r.text) > 1500:
                        return r
            except Exception:
                pass
        time.sleep(0.8)
    return None


def get_feed():
    try:
        r = proxy_get(TAG_RSS, want_image=False)
    except Exception as e:
        print("get_feed error:", e)
        return []
    if not r:
        return []
    items = []
    for block in re.findall(r"<item>(.*?)</item>", r.text, re.S | re.I):
        def pick(tag):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S | re.I)
            return html.unescape(m.group(1).strip()) if m else ""
        items.append({"title": pick("title"), "link": pick("link"),
                      "pubDate": pick("pubDate"), "cat": pick("category") or "Street"})
        if len(items) >= MAX_ITEMS:
            break
    return items


def img_b64(url, width, q=70):
    r = proxy_get(url, want_image=True)
    if not r:
        return ""
    try:
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, int(h * width / w)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def extract(page):
    imgs = []
    m = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', page) \
        or re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', page)
    if m:
        imgs.append(m.group(1))
    for u in re.findall(r'https?://www\.magnumphotos\.com/wp-content/uploads/[^"\')\s]+\.(?:jpg|jpeg|png|webp)', page):
        if u not in imgs:
            imgs.append(u)
    seen, urls = set(), []
    for u in imgs:
        b = re.sub(r'-\d+x\d+(?=\.\w+$)', '', u)
        if b not in seen:
            seen.add(b); urls.append(u)
    paras = []
    for raw in re.findall(r'<p[^>]*>(.*?)</p>', page, re.S | re.I):
        txt = html.unescape(re.sub(r'<[^>]+>', '', raw)).strip()
        if len(txt) < 60:
            continue
        low = txt.lower()
        if any(k in low for k in ["cookie", "subscribe", "newsletter", "all rights", "©", "magnum photos is", "appeared first"]):
            continue
        if txt not in paras:
            paras.append(txt)
        if len(paras) >= 8:
            break
    desc = ""
    md = re.search(r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', page) \
        or re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:description["\']', page)
    if md:
        desc = html.unescape(md.group(1)).strip()
    return urls[:IMGS_PER], paras, desc


BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}body{background:#0c0c0c;color:#eee;font-family:-apple-system,'PingFang SC',sans-serif;-webkit-font-smoothing:antialiased}a{color:inherit;text-decoration:none}
.bar{position:sticky;top:0;background:rgba(12,12,12,.92);backdrop-filter:blur(14px);padding:env(safe-area-inset-top) 18px 0;z-index:9;border-bottom:1px solid #1f1f1f}.bar .inner{padding:14px 0;display:flex;align-items:center;gap:10px}.bar h1{font-size:18px;font-weight:600}.bar p{font-size:12px;color:#888;margin-top:2px}.back{font-size:14px;color:#6cb6ff}
.wrap{max-width:640px;margin:0 auto;padding:14px}
"""
LIST_CSS = BASE_CSS + ".card{background:#151515;border:1px solid #1f1f1f;border-radius:18px;overflow:hidden;margin-bottom:18px;display:block}.cover{width:100%;display:block;background:#1a1a1a;aspect-ratio:16/10;object-fit:cover}.meta{padding:14px 16px}.cat{display:inline-block;font-size:11px;color:#e36aa0;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:6px}.title{font-size:17px;font-weight:600;line-height:1.4;margin-bottom:6px}.row{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.date{font-size:12px;color:#666}.enter{font-size:13px;color:#6cb6ff}.cnt{font-size:11px;color:#777}.foot{text-align:center;color:#555;font-size:11px;padding:24px 16px calc(24px + env(safe-area-inset-bottom))}"
POST_CSS = BASE_CSS + ".hero{width:100%;display:block;background:#1a1a1a}.head2{padding:18px 18px 6px}.cat{display:inline-block;font-size:11px;color:#e36aa0;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:8px}.ttl{font-size:22px;font-weight:600;line-height:1.35;margin-bottom:8px}.date{font-size:12px;color:#777}.body{padding:6px 18px 10px}.body p{font-size:15px;color:#cfcfcf;line-height:1.75;margin-bottom:14px}.shots img{width:100%;display:block;margin:0 0 6px;background:#1a1a1a;border-radius:10px}.foot{text-align:center;color:#555;font-size:11px;padding:20px 16px calc(30px + env(safe-area-inset-bottom))}.src{display:block;text-align:center;font-size:12px;color:#6cb6ff;padding:8px}"


AUTO_REFRESH_JS = """
(function(){
  function stamp(t){var m=t.match(/更新于\\s*([0-9: -]+)/);return m?m[1].trim():''}
  var cur=stamp(document.body.innerText||'');
  function check(){
    fetch(location.pathname+'?_ts='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.text()})
      .then(function(t){var s=stamp(t); if(s&&cur&&s!==cur){location.reload(true)} })
      .catch(function(){});
  }
  document.addEventListener('visibilitychange',function(){if(!document.hidden)check()});
  setInterval(check, 180000);
})();
"""


def pg(title, css, body):
    return (f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
            f'<meta http-equiv="Pragma" content="no-cache">'
            f'<meta http-equiv="Expires" content="0">'
            f'<meta name="apple-mobile-web-app-title" content="Magnum 街拍">'
            f'<meta name="theme-color" content="#0c0c0c">'
            f'<title>{html.escape(title)}</title><style>{css}</style></head><body>{body}'
            f'<script>{AUTO_REFRESH_JS}</script></body></html>')


def main():
    # RSS 多轮重试, 失败则不覆盖现有页面(避免清空)
    items = []
    for attempt in range(3):
        items = get_feed()
        if items:
            break
        print(f"feed empty, retry {attempt+1}/3 ...")
        time.sleep(2)
    print("feed items:", len(items))
    if not items:
        print("ABORT: RSS unreachable, keep existing pages unchanged.")
        return
    data = []
    for i, it in enumerate(items):
        page = proxy_get(it["link"], want_image=False)
        page = page.text if page else ""
        urls, paras, desc = extract(page) if page else ([], [], "")
        cover = img_b64(urls[0], COVER_W) if urls else ""
        imgs = [b for b in (img_b64(u, BODY_W) for u in urls[1:IMGS_PER]) if b]
        data.append({"title": it["title"], "date": it["pubDate"][:10], "cat": it["cat"],
                     "desc": desc, "paras": paras, "cover": cover, "images": imgs})
        print(f"  {i}: cover={'Y' if cover else 'N'} paras={len(paras)} imgs={len(imgs)}")
    upd = time.strftime("%Y-%m-%d %H:%M")
    # list
    cards = []
    for i, it in enumerate(data):
        cov = f'<img class="cover" loading="lazy" src="{it["cover"]}" alt="">' if it["cover"] else ""
        n = 1 + len(it["images"])
        cards.append(f'<a class="card" href="post-{i}.html">{cov}<div class="meta"><span class="cat">{html.escape(it["cat"])}</span><div class="title">{html.escape(it["title"])}</div><div class="row"><span class="date">{it["date"]}</span><span class="enter">看图文详情 &rarr;</span></div><div class="cnt">{n} 张图</div></div></a>')
    covers_ok = sum(1 for it in data if it["cover"])
    MIN_OK = 6  # 至少 6 篇抓到封面才允许覆盖, 否则保留旧页面(防残缺页覆盖好页)
    if covers_ok < MIN_OK:
        print(f"ABORT: only {covers_ok}/{len(data)} covers OK (<{MIN_OK}); keep existing pages unchanged.")
        return
    listbody = f'<div class="bar"><div class="inner"><div><h1>Magnum · 街拍</h1><p>Street Photography · 更新于 {upd}</p></div></div></div><div class="wrap">{"".join(cards)}</div><div class="foot">每日自动更新 · 数据来自 magnumphotos.com · 仅供个人浏览<br>更新于 {upd}</div>'
    open(os.path.join(OUTDIR, "index.html"), "w", encoding="utf-8").write(pg("Magnum 街拍", LIST_CSS, listbody))
    # posts
    for i, it in enumerate(data):
        hero = f'<img class="hero" src="{it["cover"]}" alt="">' if it["cover"] else ""
        paras = "".join(f"<p>{html.escape(p)}</p>" for p in it["paras"]) or (f"<p>{html.escape(it['desc'])}</p>" if it["desc"] else "")
        shots = "".join(f'<img loading="lazy" src="{u}" alt="">' for u in it["images"])
        body = (f'<div class="bar"><div class="inner"><a class="back" href="index.html">&larr; 返回街拍列表</a></div></div>{hero}'
                f'<div class="head2"><span class="cat">{html.escape(it["cat"])}</span><div class="ttl">{html.escape(it["title"])}</div><div class="date">{it["date"]}</div></div>'
                f'<div class="body">{paras}</div><div class="shots wrap">{shots}</div>'
                f'<a class="src" href="index.html">&larr; 返回列表</a><div class="foot">仅供个人浏览 · 数据来自 magnumphotos.com</div>')
        open(os.path.join(OUTDIR, f"post-{i}.html"), "w", encoding="utf-8").write(pg(it["title"], POST_CSS, body))
    print("DONE")


if __name__ == "__main__":
    main()
