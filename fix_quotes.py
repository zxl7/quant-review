#!/usr/bin/env python3
"""Fix Chinese quotes in render_html.py"""
import re

filepath = "daily_review/render/render_html.py"
with open(filepath, 'r') as f:
    content = f.read()

# Only replace Chinese quotes that appear INSIDE string literals
# Strategy: find lines with (\"...\u201c...\u201d...\") pattern and fix those
# Simple approach: replace all \u201c and \u201d but protect """ patterns

lines = content.split('\n')
fixed_lines = []
for line in lines:
    # Skip pure docstring delimiter lines
    stripped = line.strip()
    if stripped == '"""':
        fixed_lines.append(line)
        continue
    # Replace Chinese quotes
    fixed_lines.append(line.replace('\u201c', '\u300c').replace('\u201d', '\u300d'))

content = '\n'.join(fixed_lines)
with open(filepath, 'w') as f:
    f.write(content)

print("Fixed all Chinese quotes")
