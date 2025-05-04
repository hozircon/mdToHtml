#!/usr/bin/env python
# mdToHtml.py
# Compatible with Python ≥ 3.8
# Author: 99% ChatGPT + 1% Rizon
# Last update: 2025-04-30

import re, base64, pathlib, tempfile
import requests
import string
from pathlib import Path
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote   import footnote_plugin
from mdit_py_plugins.tasklists  import tasklists_plugin
from mdit_py_plugins.deflist    import deflist_plugin
from mdit_py_plugins.attrs      import attrs_plugin
from mdit_py_plugins.anchors   import anchors_plugin

GITHUB_CSS_URL = "https://cdn.jsdelivr.net/npm/github-markdown-css@5.2.0/github-markdown-{}.min.css"
HLJS_CSS_URL = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/styles/github-dark.min.css"
HLJS_JS_URL  = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js"

CACHE_DIR = Path(tempfile.gettempdir()) / "md_reader_cache"
CACHE_DIR.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- #
#  util：下載並快取 3rd-party 資源                                              #
# --------------------------------------------------------------------------- #
def _fetch(url: str) -> str:
    fpath = CACHE_DIR / (url.split("/")[-1])
    if not fpath.exists():
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        fpath.write_bytes(r.content)
    return fpath.read_text(encoding="utf-8")

def _get_assets() -> tuple[str, str]:
    dark_css  = _fetch(GITHUB_CSS_URL.format("dark"))
    hljs_css  = _fetch(HLJS_CSS_URL.format("-dark"))
    hljs_js   = _fetch(HLJS_JS_URL)
    return dark_css + hljs_css, hljs_js     # 只回傳 2 個值


# --------------------------------------------------------------------------- #
#  markdown → html（主要工作）                                                #
# --------------------------------------------------------------------------- #
def md_to_html(src_md: Path) -> Path:
    if not src_md.exists():
        raise FileNotFoundError(src_md)

    md_text = src_md.read_text(encoding="utf-8")

    # 1. markdown-it 解析，插件配置比照 md-reader
    md = (MarkdownIt("commonmark", {"html": True, "linkify": True, "typographer": True})
            .use(footnote_plugin)
            .use(deflist_plugin)
            .use(tasklists_plugin, {"enabled": True})
            .use(attrs_plugin)
            .use(anchors_plugin)
          )

    html_body = md.render(md_text)

    # 2. 產生 HTML —— 僅暗色主題 + 改良版面（用 .format()）
    dark_css, hljs_js = _get_assets()

    html_tpl = string.Template("""<!DOCTYPE html>
    <html lang="zh-TW">
    <head>
    <meta charset="utf-8">
    <title>$title</title>

    <!-- GitHub Markdown Dark + highlight.js Dark -->
    <style>$dark_css</style>

    <style>
        /* ===== 基本 ===== */
        html,body{
        margin:0;
        height:100%;
        font-size:15px;                      /* #4 整體字體微縮 */
        background:#0d1117;
        color:#c9d1d9;
        font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,Noto Sans,
                    sans-serif,Apple Color Emoji,Segoe UI Emoji;
        }
        body{
        display:flex;
        min-height:100vh;
        overflow-y:auto;                     /* 整頁單一捲軸，滑桿在最右側 */
        }

        /* ===== 左側 TOC ===== */
        #toc{
        box-sizing:border-box;
        flex:0 1 clamp(180px,22vw,280px);    /* #1 彈性寬度 */
        max-height:100%;
        padding:20px 10px 40px 20px;
        background:#161b22;
        border-right:1px solid #30363d;
        overflow-y:auto;
        font-size:clamp(12px,1.1vw,14px);    /* #2 隨欄寬自動縮放（最小 12、最大 14） */
        overflow-y:auto; height:100vh;
        }
        #toc a{
        display:block;
        text-decoration:none;
        color:#8b949e;
        line-height:1.5;
        }
        #toc a:hover{color:#58a6ff;}

        /* ===== 右側文章 ===== */
        .markdown-body{
        flex:1 1 auto;
        max-width:1280px;                     /* #3 內容最大寬度 */
        margin:0 auto;                       /*   置中；改成 0 即靠左 */
        padding:50px 24px 80px 24px;         /* 左右留 24px 空隙 */
        box-sizing:border-box;
        overflow-y:auto; height:100vh;                       
        }
    </style>


    </head>
    <body>

    <nav id="toc"></nav>

    <article class="markdown-body" id="content">
    $body
    </article>

    <script>$hljs_js</script>
    <script>
    document.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
    const toc=document.getElementById('toc');
    document.querySelectorAll('#content h1, #content h2, #content h3').forEach(h=>{
    const a=document.createElement('a');
    a.textContent=h.textContent;
    a.href='#'+h.id;
    a.style.marginLeft={'H1':0,'H2':12,'H3':24}[h.tagName]+'px';
    toc.appendChild(a);
    });
    </script>
    </body>
    </html>""").substitute(
        title=src_md.stem,
        dark_css=dark_css,
        body=html_body,
        hljs_js=hljs_js,
    )

    # 3. 先存檔，再把圖片 src 轉 base64
    dst_html = src_md.with_suffix(".html")
    dst_html.write_text(html_tpl, encoding="utf-8")
    _embed_images(dst_html, src_md.parent)
    return dst_html

# --------------------------------------------------------------------------- #
#  圖片轉 base64                                                               #
# --------------------------------------------------------------------------- #
def _embed_images(html_path: Path, base_dir: Path) -> None:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:") or re.match(r"^https?://", src):
            continue  # 已經是 data URI 或網路圖片
        # 解析相對路徑，支援空格 & Unicode
        img_fs_path = (base_dir / pathlib.PurePosixPath(src)).resolve()
        if not img_fs_path.exists():
            print(f"⚠ 找不到圖片檔：{img_fs_path}")
            continue
        mime = "image/" + img_fs_path.suffix.lstrip(".").lower()
        data_uri = f"data:{mime};base64," + base64.b64encode(img_fs_path.read_bytes()).decode()
        img["src"] = data_uri
    html_path.write_text(str(soup), encoding="utf-8")

# ─────────────────────────────────────────────────────────────
# GUI 與命令列入口

import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import sys

def open_file():
    """選檔並呼叫既有 md_to_html()"""
    md_path = filedialog.askopenfilename(
        title="選擇 Markdown 檔",
        filetypes=[("Markdown files", "*.md *.markdown"), ("All files", "*.*")]
    )
    if not md_path:
        return                      # 使用者取消
    try:
        html_path = md_to_html(Path(md_path))
        messagebox.showinfo("完成", f"已產生：\n{html_path}")
    except Exception as e:
        messagebox.showerror("轉換失敗", str(e))

def create_gui():
    root = tk.Tk()
    root.title("Markdown ➜ HTML 轉換器")
    root.geometry("360x160")
    root.eval('tk::PlaceWindow . center')  # 視窗置中

    label = tk.Label(
        root,
        text="請選擇要轉換的 Markdown 檔案",
        font=("Microsoft JhengHei", 12)
    )
    label.pack(pady=20)

    button = tk.Button(
        root,
        text="選擇檔案並轉換",
        font=("Microsoft JhengHei", 12),
        command=open_file
    )
    button.pack(pady=10)

    root.mainloop()

# ────────────────────────  命令列 / GUI 入口  ───────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Markdown ➜ 離線 HTML 轉換器（不給檔名就開 GUI）"
    )
    ap.add_argument("markdown", nargs="?", help=".md 檔路徑")
    args = ap.parse_args()

    if args.markdown:                          # 命令列模式
        try:
            out = md_to_html(Path(args.markdown))
            print("產生：", out)
        except Exception as e:
            print("失敗：", e)
            sys.exit(1)
    else:                                      # 無參數 → GUI
        create_gui()