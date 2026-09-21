"""Export the static landing page as one HTML file. Python standard library only."""
from pathlib import Path
import base64
import re
import sys

root = Path(__file__).resolve().parents[1]
source = root / "site"
destination = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "dist" / "Rasam-landing.html"
html = (source / "index.html").read_text(encoding="utf-8")
css = (source / "styles.css").read_text(encoding="utf-8").replace('@charset "UTF-8";', '')
js = (source / "script.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
html = html.replace('<link rel="stylesheet" href="styles.css">', "<style>\n" + css + "\n</style>")
html = html.replace('<script src="script.js" defer></script>', '')
html = html.replace('</body>', "<script>\n" + js + "\n</script>\n</body>")
# A single-file copy links to setup; the full site has its own working demo.
def workbench_link(match):
    label = match.group(3).replace('Try the workbench', 'Get the workbench')
    return ('<a' + match.group(1) + 'href="https://github.com/20SHA07/Rasam/tree/main/workbench"'
            + match.group(2) + '>' + label + '</a>')
html = re.sub(r'<a([^>]*?)href="(?:\./)?workbench\.html"([^>]*)>(.*?)</a>', workbench_link, html, flags=re.S)
favicon = base64.b64encode((source / 'favicon.svg').read_bytes()).decode('ascii')
html = html.replace('href="favicon.svg"', 'href="data:image/svg+xml;base64,' + favicon + '"')
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(html, encoding="utf-8")
print(destination)
