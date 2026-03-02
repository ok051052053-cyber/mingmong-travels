import os
import json
from datetime import datetime
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

KEYWORD = os.environ.get("KEYWORD", "korea travel tips")
slug = KEYWORD.lower().replace(" ", "-")

# 글 생성
prompt = f"""
Write a 1200+ word SEO optimized travel blog article targeting US and European travelers.
Topic: {KEYWORD}
Include sections, h2, h3, FAQ, tips, checklist.
Friendly tone.
"""

res = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}]
)

content = res.choices[0].message.content

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{KEYWORD}</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<main class="container">
<h1>{KEYWORD}</h1>

<img src="../assets/posts/{slug}/1.jpg">
<img src="../assets/posts/{slug}/2.jpg">
<img src="../assets/posts/{slug}/3.jpg">

{content}
</main>
</body>
</html>
"""

# 파일 생성
os.makedirs(f"posts", exist_ok=True)
with open(f"posts/{slug}.html", "w", encoding="utf-8") as f:
    f.write(html)

# posts.json 업데이트
data = []
if os.path.exists("posts.json"):
    with open("posts.json","r",encoding="utf-8") as f:
        data = json.load(f)

data.insert(0,{
    "slug": slug,
    "title": KEYWORD.title(),
    "description": KEYWORD,
    "category": "Korea Travel Experiences",
    "date": datetime.today().strftime("%Y-%m-%d")
})

with open("posts.json","w",encoding="utf-8") as f:
    json.dump(data,f,indent=2)

print("POST CREATED:", slug)
