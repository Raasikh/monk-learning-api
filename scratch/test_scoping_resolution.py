import os
import requests
from dotenv import load_dotenv, dotenv_values

load_dotenv('.env')
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

sp_key = (os.getenv("SUPABASE_SECRET_KEY") or "").strip("\"'")
base_url = "https://monk-learning-api-production.up.railway.app"

# Register subtopic index and scope session on Railway
headers = {"Content-Type": "application/json"}
subtopics = [
    ("torque-and-angular-momentum-test-123", "Torque and Angular Momentum", "Rotational Motion", "Physics"),
    ("vsepr-theory-and-molecular-shapes-test-123", "VSEPR Theory and Molecular Shapes", "Chemical Bonding and Molecular Structure", "Chemistry"),
    ("definite-integration-by-substitution-test-123", "Definite Integration by Substitution", "Integrals", "Maths"),
    ("generation-and-conduction-of-nerve-impulse-test-123", "Generation and Conduction of Nerve Impulse", "Neural Control and Coordination", "Biology")
]

for key, title, chap, subj in subtopics:
    # 1. Register index
    sp_url = "https://tgbknrmnjwiokraddurx.supabase.co"
    sp_key = os.getenv("SUPABASE_SECRET_KEY", "")
    sp_headers = {"apikey": sp_key, "Authorization": f"Bearer {sp_key}", "Content-Type": "application/json"}

    # 1. Register index
    reg_res = requests.post(f"{sp_url}/rest/v1/subtopic_index", json={
        "chapter_id": "c7608db0-77a8-48b9-8c01-ef0db3031dd5",
        "subtopic": f"{title} RW-9999",
        "subtopic_key": key
    }, headers=sp_headers)
    chap_id = "c7608db0-77a8-48b9-8c01-ef0db3031dd5"
    
from scripts.full_session_harness import mint_real_supabase_jwt

token = mint_real_supabase_jwt()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

for key, title, chap, subj in subtopics:
    # 1. Register index
    reg_res = requests.post(f"{sp_url}/rest/v1/subtopic_index", json={
        "chapter_id": "c7608db0-77a8-48b9-8c01-ef0db3031dd5",
        "subtopic": f"{title} RW-9999",
        "subtopic_key": key
    }, headers=sp_headers)
    chap_id = "c7608db0-77a8-48b9-8c01-ef0db3031dd5"

    # Start session
    s_res = requests.post(f"{base_url}/drona/session/start", json={"chapter_id": chap_id}, headers=headers)
    sess_id = s_res.json().get("session_id") if s_res.status_code == 200 else None

    # Scope session
    scope_res = requests.post(f"{base_url}/drona/session/scope", json={
        "session_id": sess_id,
        "chapter_id": chap_id,
        "utterance": key
    }, headers=headers)
    
    if scope_res.status_code == 200:
        data = scope_res.json()
        print(f"  ✓ [{subj.upper()}] Subtopic Key: '{key[:40]}' -> Phase: '{data.get('phase')}', Plan Ready: {data.get('plan_ready')}, Subtopic: '{data.get('subtopic')}'")
    else:
        print(f"  ❌ [{subj.upper()}] Scoping HTTP {scope_res.status_code}: {scope_res.text[:150]}")
