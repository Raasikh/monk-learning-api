import os
import glob
import re
import json
from typing import Dict, List, Optional
import fitz  # PyMuPDF
import tiktoken
from openai import OpenAI
from app.db import supabase

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tokenizer = tiktoken.get_encoding("cl100k_base")

def get_embedding(text: str) -> List[float]:
    """Generates 1536-dimensional embedding using text-embedding-3-small."""
    res = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return res.data[0].embedding

def sanitize_text(text: str) -> str:
    """Strips NUL bytes and invalid Postgres text control characters."""
    if not text:
        return ""
    text = text.replace('\x00', '').replace('\u0000', '')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()

def chunk_text(text: str, max_tokens: int = 800, overlap: int = 100) -> List[str]:
    """Chunks text into max_tokens with overlap, attempting paragraph splits."""
    text = sanitize_text(text)
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for p in paragraphs:
        p_text = sanitize_text(p)
        if not p_text:
            continue

        prospective = (current_chunk + "\n\n" + p_text).strip()
        tokens = len(tokenizer.encode(prospective))

        if tokens <= max_tokens:
            current_chunk = prospective
        else:
            if current_chunk:
                chunks.append(current_chunk)
            
            p_tokens = tokenizer.encode(p_text)
            if len(p_tokens) > max_tokens:
                step = max_tokens - overlap
                for i in range(0, len(p_tokens), step):
                    window = tokenizer.decode(p_tokens[i:i + max_tokens])
                    chunks.append(sanitize_text(window))
                current_chunk = ""
            else:
                current_chunk = p_text

    if current_chunk:
        chunks.append(current_chunk)

    return [c for c in chunks if len(c) > 10]

def build_chapter_matcher():
    """Fetches chapters and chapter_aliases from Supabase."""
    res = supabase.table('chapters').select('id, name, subject, class_level, slug').execute()
    chapters = res.data or []
    
    chapter_lookup = []
    for c in chapters:
        norm_name = re.sub(r'[^a-z0-9]+', ' ', c['name'].lower()).strip()
        chapter_lookup.append({
            'id': c['id'],
            'name': c['name'],
            'norm_name': norm_name,
            'subject': c['subject'].lower(),
            'class_level': c['class_level']
        })

    # Fetch chapter_aliases
    res_alias = supabase.table('chapter_aliases').select('chapter_id, alias_norm').execute()
    alias_lookup = {}
    for a in (res_alias.data or []):
        alias_lookup[a['alias_norm']] = a['chapter_id']

    return chapter_lookup, alias_lookup

def match_pdf_to_chapter(pdf_path: str, chapter_lookup: List[dict], alias_lookup: Dict[str, str]) -> tuple[Optional[dict], str]:
    """Matches PDF file path to a canonical chapter using direct match, aliases, or returns (None, skip_reason)."""
    filename = os.path.basename(pdf_path)
    parent_dir = os.path.basename(os.path.dirname(pdf_path)).lower()

    subj = None
    if 'phys' in parent_dir:
        subj = 'physics'
    elif 'chem' in parent_dir:
        subj = 'chemistry'
    elif 'math' in parent_dir:
        subj = 'mathematics'
    elif 'bio' in parent_dir:
        subj = 'biology'

    class_level = 11 if '11' in parent_dir else (12 if '12' in parent_dir else None)

    if not subj or not class_level:
        return None, f"Could not determine subject/class_level from directory '{parent_dir}'"

    norm_filename = re.sub(r'[^a-z0-9]+', ' ', filename.lower()).strip()

    # 1. Exact lookup in chapter_aliases
    if norm_filename in alias_lookup:
        cid = alias_lookup[norm_filename]
        # Find matched chapter object
        for c in chapter_lookup:
            if c['id'] == cid:
                return c, "matched_via_alias"

    # 2. Direct title match among candidates
    candidates = [c for c in chapter_lookup if c['subject'] == subj and c['class_level'] == class_level]

    best_match = None
    best_score = 0

    for c in candidates:
        words = [w for w in c['norm_name'].split() if len(w) > 3]
        matched_words = sum(1 for w in words if w in norm_filename)
        score = matched_words / len(words) if words else 0
        if score > best_score and score >= 0.4:
            best_score = score
            best_match = c

    if best_match:
        return best_match, "matched_via_title"
    else:
        return None, f"No confident chapter match for filename '{filename}' in {subj.upper()} Class {class_level}"

def run_ingestion(target_filenames: Optional[List[str]] = None):
    master_dir = '/Users/raasikhnaveed/Desktop/Master Content'
    print(f"Scanning master PDFs in {master_dir}...")

    all_pdf_files = glob.glob(f"{master_dir}/**/*.pdf", recursive=True)
    if target_filenames:
        pdf_files = [p for p in all_pdf_files if os.path.basename(p) in target_filenames]
    else:
        pdf_files = all_pdf_files

    print(f"Found {len(pdf_files)} PDF files to process.")

    chapter_lookup, alias_lookup = build_chapter_matcher()

    skipped_logs = []
    processed_count = 0
    total_chunks_inserted = 0
    subject_chunks_count: Dict[str, int] = {'physics': 0, 'chemistry': 0, 'mathematics': 0, 'biology': 0}

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        matched_chapter, reason = match_pdf_to_chapter(pdf_path, chapter_lookup, alias_lookup)

        if not matched_chapter:
            skipped_logs.append({'file': filename, 'reason': reason})
            print(f"[SKIP] {filename}: {reason}")
            continue

        cid = matched_chapter['id']
        subj = matched_chapter['subject']
        class_lvl = matched_chapter['class_level']

        try:
            doc = fitz.open(pdf_path)
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            doc.close()
        except Exception as e:
            skipped_logs.append({'file': filename, 'reason': f"PDF read error: {e}"})
            print(f"[ERROR] Failed to read PDF {filename}: {e}")
            continue

        full_text = sanitize_text(full_text)

        if len(full_text) < 100:
            skipped_logs.append({'file': filename, 'reason': "Extracted text under 100 characters"})
            print(f"[SKIP] {filename}: Text under 100 characters")
            continue

        chunks = chunk_text(full_text, max_tokens=800, overlap=100)
        print(f"[INGEST] {filename} -> Chapter '{matched_chapter['name']}' ({subj.upper()}): {len(chunks)} chunks")

        # Check existing chunks in Supabase for idempotency
        existing_res = supabase.table('pdf_chunks').select('chunk_index').eq('source_file', filename).execute()
        existing_indices = {r['chunk_index'] for r in (existing_res.data or [])}

        records_to_insert = []
        for idx, chunk_str in enumerate(chunks):
            if idx in existing_indices:
                continue

            chunk_str = sanitize_text(chunk_str)
            try:
                emb = get_embedding(chunk_str)
                records_to_insert.append({
                    'chapter_id': cid,
                    'subject': subj,
                    'class_level': class_lvl,
                    'source_file': filename,
                    'page_start': 1,
                    'page_end': 1,
                    'chunk_index': idx,
                    'content': chunk_str,
                    'embedding': emb
                })
            except Exception as e:
                print(f"Error embedding chunk {idx} of {filename}: {e}")

        if records_to_insert:
            for i in range(0, len(records_to_insert), 50):
                b = records_to_insert[i:i + 50]
                res = supabase.table('pdf_chunks').insert(b).execute()
                total_chunks_inserted += len(res.data or [])

        subject_chunks_count[subj] = subject_chunks_count.get(subj, 0) + len(chunks)
        processed_count += 1

    print("\n=== RE-INGESTION SUMMARY ===")
    print(f"Processed Files: {processed_count} / {len(pdf_files)}")
    print(f"Skipped Files: {len(skipped_logs)}")
    print(f"New Chunks Inserted: {total_chunks_inserted}")

if __name__ == '__main__':
    # Target 10 approved skipped files for re-ingest
    target_10 = [
        'b11_ch05_morphology_MASTER.pdf',
        'b11_ch11_photosynthesis-2.pdf',
        'chapter3_Everything.pdf',
        'ch11_3dgeom_master.pdf',
        'c11_ch03_periodicity_chapter-2.pdf',
        'c11_ch02_atom_chapter-2.pdf',
        'ch02_inverse_trig_master.pdf',
        'b12_ch08_microbes_MASTER.pdf',
        'm12_ch08_appint_subtopics-01-02-03_MASTER.pdf',
        'chapter11-2.pdf'
    ]
    run_ingestion(target_10)
