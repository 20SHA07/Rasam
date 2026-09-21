"""Bundle Rasam into one offline HTML file. Python 3 standard library only."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'Rasam.html'
html = (ROOT / 'index.html').read_text(encoding='utf-8')
html = html.replace('<link rel="stylesheet" href="styles.css">', '<style>\n' + (ROOT / 'styles.css').read_text(encoding='utf-8') + '\n</style>')
for name in ('export.js', 'ai-client.js', 'app.js'):
    code = (ROOT / name).read_text(encoding='utf-8').replace('</script', '<\\/script')
    html = html.replace('<script src="' + name + '"></script>', '<script>\n' + code + '\n</script>')
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(html, encoding='utf-8')
print(str(destination))
