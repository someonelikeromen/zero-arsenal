import json

path = r'c:\Users\22134\.cursor\projects\e-plu\agent-transcripts\5881117b-8baf-4992-8026-30e5b1baaa6c\subagents\07a669e6-2685-4459-af7a-e76cccf4dfda.jsonl'
with open(path, encoding='utf-8') as f:
    lines = f.readlines()
obj = json.loads(lines[7])
content = obj['message']['content']
for block in content:
    if block.get('type') == 'text':
        txt = block['text']
        start = txt.find('```json')
        end = txt.find('```', start + 7)
        if start != -1 and end != -1:
            json_str = txt[start + 7:end].strip()
            data = json.loads(json_str)
            out_path = r'E:\plu\zero-arsenal\docs\comparison\raw\E2-novelai-chub-kobold.json'
            with open(out_path, 'w', encoding='utf-8') as out:
                json.dump(data, out, ensure_ascii=False, indent=2)
            print(f'Saved {len(data)} project entries')

# Also save the priority matrix section
for block in content:
    if block.get('type') == 'text':
        txt = block['text']
        matrix_start = txt.find('## 横向综合建议')
        if matrix_start != -1:
            matrix_path = r'E:\plu\zero-arsenal\docs\comparison\raw\E2-priority-matrix.md'
            with open(matrix_path, 'w', encoding='utf-8') as out:
                out.write(txt[matrix_start:])
            print(f'Saved priority matrix ({len(txt[matrix_start:])} chars)')
