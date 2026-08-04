import os
import glob
import hashlib
import subprocess
from string import Template
from typing import Dict

_PROMPTS_CACHE: Dict[str, Template] = {}
_PROMPT_VERSION: str = "unknown"

def get_git_short_sha() -> str:
    """Computes a git short SHA of the prompts/ directory or returns a deterministic hash."""
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "prompts")
    prompts_dir = os.path.abspath(prompts_dir)
    try:
        res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%h", "--", prompts_dir],
            capture_output=True,
            text=True,
            check=True
        )
        sha = res.stdout.strip()
        if sha:
            return sha
    except Exception:
        pass

    # Fallback to hashing prompt contents deterministically if git is unavailable
    hasher = hashlib.sha256()
    for fname in sorted(glob.glob(os.path.join(prompts_dir, "*.md"))):
        with open(fname, "rb") as f:
            hasher.update(f.read())
    return hasher.hexdigest()[:8]

def load_prompts() -> None:
    """Loads all prompt templates from prompts/ into memory at FastAPI startup."""
    global _PROMPTS_CACHE, _PROMPT_VERSION
    prompts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "prompts"))
    
    if not os.path.exists(prompts_dir):
        raise RuntimeError(f"Prompts directory not found at: {prompts_dir}")

    _PROMPTS_CACHE.clear()
    for filepath in glob.glob(os.path.join(prompts_dir, "*.md")):
        name = os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            _PROMPTS_CACHE[name] = Template(content)

    _PROMPT_VERSION = get_git_short_sha()

def get_prompt_template(name: str) -> Template:
    """Retrieves a loaded prompt Template by name (e.g., 'scoping', 'planner', 'tutor')."""
    if not _PROMPTS_CACHE:
        load_prompts()
    if name not in _PROMPTS_CACHE:
        raise KeyError(f"Prompt template '{name}' not found. Available: {list(_PROMPTS_CACHE.keys())}")
    return _PROMPTS_CACHE[name]

def load_prompt(name: str) -> str:
    """Loads and returns raw prompt markdown text by name (e.g. 'scoping.md' or 'scoping')."""
    clean_name = os.path.splitext(name)[0]
    tmpl = get_prompt_template(clean_name)
    return tmpl.template

def get_prompt_version() -> str:
    """Returns the prompt_version git short SHA."""
    global _PROMPT_VERSION
    if _PROMPT_VERSION == "unknown":
        _PROMPT_VERSION = get_git_short_sha()
    return _PROMPT_VERSION

# Automatically initialize on module import
load_prompts()
