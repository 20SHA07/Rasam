"""Build the local app and public manual preview using the standard library."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ROOT / "source/build.py"), str(ROOT / "Rasam.html")], check=True)
html = (ROOT / "Rasam.html").read_text(encoding="utf-8")
html = html.replace("<title>Rasam · Invoice workbench</title>", "<title>Rasam · Workbench preview</title>")
html = html.replace("</head>", """<style>
.site-preview-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:#e0eee4;color:#183e2b;border-bottom:1px solid #bdcfc1;padding:12px 24px;font-size:13px;line-height:1.5}
.site-preview-banner strong{font-weight:650}
.site-preview-banner nav{display:flex;gap:20px;flex-wrap:wrap}
.site-preview-banner a{text-decoration:underline;text-underline-offset:3px}
@media(max-width:640px){.site-preview-banner{padding:12px 16px;font-size:12px}}
</style>
<script>window.RASAM_STATIC_PREVIEW = true;</script>
</head>""")
html = html.replace("<body>", """<body>
  <div class="site-preview-banner" role="region" aria-label="Preview information">
    <strong>Workbench preview · OCR and AI reading run in the local app</strong>
    <nav aria-label="Preview navigation"><a href="./index.html">Back to Rasam</a><a href="https://github.com/20SHA07/Rasam/tree/main/workbench">Get the local app</a></nav>
  </div>""")
html = html.replace("return !global.RASAM_INLINE_PREVIEW && global.location &&", "return !global.RASAM_STATIC_PREVIEW && !global.RASAM_INLINE_PREVIEW && global.location &&")
html = html.replace("Extract the starter package and run its launcher. This chat preview and a directly opened HTML file support manual entry.", "Get the local app from the link above and run its launcher. This website preview supports samples, manual review, and Excel export.")
html = html.replace("AI reading runs in the localhost app, not in the chat preview or a directly opened file.", "AI reading runs in the local app. Use Get the local app above to set it up.")
preview = ROOT.parent / "site/workbench.html"
preview.parent.mkdir(parents=True, exist_ok=True)
preview.write_text(html, encoding="utf-8")
print(preview)
