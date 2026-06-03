import json, sys

path = r'c:\Users\22134\.cursor\projects\e-plu\agent-transcripts\5881117b-8baf-4992-8026-30e5b1baaa6c\subagents\256e6edc-f4e6-4aa2-ac02-5b26f4d857d0.jsonl'
with open(path, encoding='utf-8') as f:
    lines = f.readlines()

print(f'Total lines: {len(lines)}')
all_text = []
for i, line in enumerate(lines):
    obj = json.loads(line)
    role = obj.get('role', '?')
    msg = obj.get('message', {})
    if msg:
        content = msg.get('content', [])
        for block in (content if isinstance(content, list) else []):
            if isinstance(block, dict) and block.get('type') == 'text':
                txt = block.get('text', '')
                if len(txt) > 200:
                    print(f'Line {i} [{role}] len={len(txt)}')
                    all_text.append((i, role, txt))

# Save the largest assistant message (likely the full report)
assistant_texts = [(i, role, txt) for i, role, txt in all_text if role == 'assistant']
if assistant_texts:
    # Find the longest one
    longest = max(assistant_texts, key=lambda x: len(x[2]))
    out_path = r'E:\plu\zero-arsenal\docs\comparison\raw\E1-raw.txt'
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(longest[2])
    print(f'\nSaved longest assistant message ({len(longest[2])} chars) from line {longest[0]}')
    
    # Try to extract JSON if present
    txt = longest[2]
    start = txt.find('```json')
    if start != -1:
        end = txt.find('```', start + 7)
        if end != -1:
            json_str = txt[start + 7:end].strip()
            try:
                data = json.loads(json_str)
                out_json = r'E:\plu\zero-arsenal\docs\comparison\raw\E1-sillytavern-openwebui.json'
                with open(out_json, 'w', encoding='utf-8') as out:
                    json.dump(data, out, ensure_ascii=False, indent=2)
                print(f'Extracted JSON with {len(data) if isinstance(data, list) else 1} entries')
            except Exception as e:
                print(f'JSON parse error: {e}')
    else:
        print('No JSON block found, saving full text as-is')
