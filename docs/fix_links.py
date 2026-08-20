import re

f = open('index.html', encoding='utf-8').read()

replacements = {
    'href="docs/SPEC.md"': 'href="SPEC.md"',
    'href="docs/CONFIGURATION.md"': 'href="CONFIGURATION.md"',
    'href="docs/ARCHITECTURE.md"': 'href="ARCHITECTURE.md"',
    'href="docs/DECISIONS.md"': 'href="DECISIONS.md"',
    'href="docs/ANALYTICS.md"': 'href="ANALYTICS.md"',
    'href="README.md"': 'href="https://github.com/Xarawg/agent-forge#readme"',
    'href="LICENSE"': 'href="https://github.com/Xarawg/agent-forge/blob/main/LICENSE"',
    'href="https://github.com"': 'href="https://github.com/Xarawg/agent-forge"',
}

for old, new in replacements.items():
    f = f.replace(old, new)

open('index.html', 'w', encoding='utf-8').write(f)
print('done')
