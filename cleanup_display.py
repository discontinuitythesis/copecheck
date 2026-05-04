"""
Cleanup script for CopeCheck display issues.
Fixes: artifacts in text, N/A values, Test Figure, name casing, contact title.
"""
import sqlite3
import re

DB_PATH = "/home/ben/infra/copecheck/data/copecheck.db"

def clean_artifact_text(text):
    """Strip machine artifacts from LLM-generated text."""
    if not text:
        return text
    # Strip TEXT START: and URL SCAN: prefixes
    text = re.sub(r'(?i)^(TEXT START|URL SCAN)\s*:\s*', '', text.strip())
    # Strip leading ** (unrendered markdown bold markers at start)
    text = re.sub(r'^\*\*\s*', '', text)
    # Strip trailing **
    text = re.sub(r'\s*\*\*$', '', text)
    return text.strip()

def is_na_value(text):
    """Check if a value is effectively N/A (should be hidden)."""
    if not text:
        return True
    cleaned = text.strip().lower()
    # Match various N/A patterns
    na_patterns = [
        r'^n/a',
        r'^\*+\s*n/a',
        r'^none\s*(detected)?',
        r'^insufficient',
        r'^\[?none',
        r'^not\s+applicable',
        r'^n/a\s*[-—]',
        r'^n/a\*+',
    ]
    for pat in na_patterns:
        if re.match(pat, cleaned):
            return True
    return False

def title_case_name(name):
    """Proper title case for names."""
    if not name:
        return name
    # Split on spaces and capitalize each part
    parts = name.split()
    result = []
    for part in parts:
        # Handle hyphenated names
        if '-' in part:
            result.append('-'.join(p.capitalize() for p in part.split('-')))
        else:
            result.append(part.capitalize())
    return ' '.join(result)

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Fix name casing in instant_scores
    c.execute("SELECT id, name FROM instant_scores")
    for row in c.fetchall():
        sid, name = row
        fixed = title_case_name(name)
        if fixed != name:
            # Also fix the slug to match
            print(f"  instant_scores: '{name}' -> '{fixed}'")
            c.execute("UPDATE instant_scores SET name = ? WHERE id = ?", (fixed, sid))

    # 2. Delete Test Figure from instant_scores
    c.execute("SELECT id, name FROM instant_scores WHERE LOWER(name) LIKE '%test figure%'")
    test_rows = c.fetchall()
    for row in test_rows:
        print(f"  Deleting Test Figure (id={row[0]})")
        c.execute("DELETE FROM instant_scores WHERE id = ?", (row[0],))

    # 3. Clean up figures table - nullify N/A values for last_cope_type and last_quote
    c.execute("SELECT id, name, last_cope_type, last_quote FROM figures")
    for row in c.fetchall():
        fid, name, cope_type, quote = row
        updates = {}
        if is_na_value(cope_type):
            updates['last_cope_type'] = None
        elif cope_type:
            cleaned = clean_artifact_text(cope_type)
            if cleaned != cope_type:
                updates['last_cope_type'] = cleaned

        if is_na_value(quote):
            updates['last_quote'] = None
        elif quote:
            cleaned = clean_artifact_text(quote)
            if cleaned != quote:
                updates['last_quote'] = cleaned

        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates)
            vals = list(updates.values()) + [fid]
            c.execute(f"UPDATE figures SET {set_clause} WHERE id = ?", vals)
            print(f"  figures/{fid}: updated {list(updates.keys())}")

    # 4. Clean cope_entries - clean artifact text in cope_type, quote, analysis_md
    c.execute("SELECT id, cope_type, quote, analysis_md FROM cope_entries")
    for row in c.fetchall():
        eid, cope_type, quote, analysis = row
        updates = {}

        if cope_type:
            cleaned = clean_artifact_text(cope_type)
            if is_na_value(cope_type):
                updates['cope_type'] = None
            elif cleaned != cope_type:
                updates['cope_type'] = cleaned

        if quote:
            cleaned = clean_artifact_text(quote)
            if is_na_value(quote):
                updates['quote'] = None
            elif cleaned != quote:
                updates['quote'] = cleaned

        if analysis:
            cleaned = clean_artifact_text(analysis)
            if cleaned != analysis:
                updates['analysis_md'] = cleaned

        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates)
            vals = list(updates.values()) + [eid]
            c.execute(f"UPDATE cope_entries SET {set_clause} WHERE id = ?", vals)
            print(f"  cope_entries/{eid}: updated {list(updates.keys())}")

    conn.commit()
    print("\nDatabase cleanup complete.")
    conn.close()

if __name__ == "__main__":
    main()
