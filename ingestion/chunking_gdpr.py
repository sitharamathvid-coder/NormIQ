import pandas as pd
import json

df = pd.read_csv('data/raw/gdpr_text.csv')

chunks = []
for _, row in df.iterrows():
    article    = int(row['article'])
    sub        = int(row['sub_article']) if pd.notna(row['sub_article']) else None
    text       = str(row['gdpr_text'])
    
    # Build precise citation
    if sub:
        citation = f"GDPR Article {article}({sub})"
    else:
        citation = f"GDPR Article {article}"
    
    chunk = {
        "id":       f"gdpr-art{article}-{sub or 0}",
        "text":     text,
        "citation": citation,
        "metadata": {
            "regulation":    "GDPR",
            "jurisdiction":  "EU",
            "section_type":  "Article",
            "section_title": str(row.get('article_title', '')),
            "citation":      citation,
            "article":       article,
            "sub_article":   sub,
            "chapter":       int(row['chapter']),
            "href":          str(row.get('href', '')),
            "is_deprecated": False
        }
    }
    chunks.append(chunk)

print(f"Total chunks: {len(chunks)}")
print(f"Sample: {chunks[6]['citation']} — {chunks[6]['text'][:80]}")

with open('data/gdpr_rechunked.json', 'w') as f:
    json.dump(chunks, f, indent=2)
print("Saved!")