#!/usr/bin/env python3
"""Fix CopeCheck scoring to use recency-weighted average with noise filter."""

with open("/home/ben/infra/copecheck/db.py", "r") as f:
    lines = f.readlines()

# Find the scoring block
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if "SELECT cope_score, created_at FROM cope_entries" in line and start_idx is None:
        for j in range(i, max(i-3, 0), -1):
            if "cur = c.execute" in lines[j]:
                start_idx = j
                break
    if start_idx and "new_avg = round(total_s" in line:
        end_idx = i
        break

if start_idx is None or end_idx is None:
    print(f"Could not find scoring block: start={start_idx}, end={end_idx}")
    exit(1)

print(f"Found scoring block at lines {start_idx+1}-{end_idx+1}")

indent = "        "
new_block = []
new_block.append(indent + 'cur = c.execute(\n')
new_block.append(indent + '    """SELECT cope_score, created_at FROM cope_entries\n')
new_block.append(indent + '       WHERE figure_id = ? ORDER BY created_at DESC""",\n')
new_block.append(indent + '    (figure_id,),\n')
new_block.append(indent + ')\n')
new_block.append(indent + 'entries = cur.fetchall()\n')
new_block.append(indent + 'if entries:\n')
new_block.append(indent + '    # Recency-weighted scoring with noise filter\n')
new_block.append(indent + '    # - Drop entries scoring < 15 (noise / irrelevant mentions)\n')
new_block.append(indent + '    # - 14-day half-life: entries lose half their weight every 2 weeks\n')
new_block.append(indent + '    import math\n')
new_block.append(indent + '    from datetime import datetime, timezone\n')
new_block.append(indent + '    now = datetime.now(timezone.utc)\n')
new_block.append(indent + '    HALF_LIFE_DAYS = 14.0\n')
new_block.append(indent + '    DECAY = math.log(2) / HALF_LIFE_DAYS\n')
new_block.append(indent + '    MIN_SCORE = 15  # noise threshold\n')
new_block.append(indent + '    total_w = 0.0\n')
new_block.append(indent + '    total_s = 0.0\n')
new_block.append(indent + '    for e in entries:\n')
new_block.append(indent + '        if e["cope_score"] < MIN_SCORE:\n')
new_block.append(indent + '            continue  # skip noise\n')
new_block.append(indent + '        try:\n')
new_block.append(indent + '            ts = datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))\n')
new_block.append(indent + '            if ts.tzinfo is None:\n')
new_block.append(indent + '                ts = ts.replace(tzinfo=timezone.utc)\n')
new_block.append(indent + '            age_days = (now - ts).total_seconds() / 86400.0\n')
new_block.append(indent + '        except Exception:\n')
new_block.append(indent + '            age_days = 30.0\n')
new_block.append(indent + '        w = math.exp(-DECAY * age_days)\n')
new_block.append(indent + '        total_w += w\n')
new_block.append(indent + '        total_s += e["cope_score"] * w\n')
new_block.append(indent + '    if total_w > 0:\n')
new_block.append(indent + '        new_avg = round(total_s / total_w, 1)\n')
new_block.append(indent + '    else:\n')
new_block.append(indent + '        all_scores = [e["cope_score"] for e in entries]\n')
new_block.append(indent + '        new_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else cope_score\n')

lines[start_idx:end_idx+1] = new_block

with open("/home/ben/infra/copecheck/db.py", "w") as f:
    f.writelines(lines)

print("Scoring updated successfully")
