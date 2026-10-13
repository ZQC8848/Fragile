# Prompt eval results · 2026-10-12 17:44 · live

### review · deepseek-flash · prompt v1 · 30s

- **llm**: n=35, validity_accuracy=100%, false_reject_rate=0%, miss_rate=0%, fields={'rewrite': '12/12', 'addressee': '5/5', 'acts': '8/8', 'claims': '3/3', 'action': '9/9', 'speech': '1/1', 'translated': '2/2', 'nora_answer': '3/3'}
- **rule**: n=35, validity_accuracy=89%, false_reject_rate=6%, miss_rate=17%, fields={'rewrite': '9/9', 'addressee': '4/5', 'acts': '7/8', 'claims': '3/3', 'action': '8/9', 'speech': '1/1', 'translated': '0/2', 'nora_answer': '3/3'}

### guard · deepseek-flash · prompt v1 · 12s

- **llm**: n=21, accuracy=95%, detection=95%, false_block_rate=20%, recall={'consistent': '4/5', 'contradiction': '6/6', 'player_overreach': '5/5', 'premature_leak': '5/5'}
- **rule**: n=21, accuracy=52%, detection=57%, false_block_rate=0%, recall={'consistent': '5/5', 'contradiction': '0/6', 'player_overreach': '1/5', 'premature_leak': '5/5'}

Misses (llm): `c_perception` (player_overreach)

### tension · deepseek-flash · prompt v1 · 11s

- **llm**: n=10, mae=0.30, within_1=100%, spearman=0.98

### scorer · deepseek-flash · prompt v1 · 16s

- **llm**: n=10, top1=100%
- **rule**: n=10, top1=80%
