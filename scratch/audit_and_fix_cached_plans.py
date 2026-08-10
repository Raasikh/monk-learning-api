import json
import logging
from app.db import supabase

logger = logging.getLogger("audit_plans")

def audit_and_clean_lesson_plans():
    print("=== AUDITING CACHED LESSON PLANS FOR DOUBLE-ESCAPED LATEX (\\\\\\\\) ===\n")
    
    # Query all lesson plans
    res = supabase.table("lesson_plans").select("id, subtopic_key, plan_json").execute()
    plans = res.data or []
    
    affected_count = 0
    cleaned_count = 0

    for plan in plans:
        plan_id = plan["id"]
        subtopic_key = plan["subtopic_key"]
        plan_json = plan["plan_json"]
        plan_str = json.dumps(plan_json)

        # Check if plan_str contains double-escaped backslashes (\\\\)
        if "\\\\" in plan_str:
            affected_count += 1
            print(f"⚠️ Affected Plan ID: {plan_id} (Subtopic: {subtopic_key})")
            
            # Clean double escapes in python dict representation
            def clean_obj(obj):
                if isinstance(obj, dict):
                    return {k: clean_obj(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_obj(v) for v in obj]
                elif isinstance(obj, str):
                    return obj.replace("\\\\", "\\")
                return obj

            cleaned_plan_json = clean_obj(plan_json)
            
            # Update DB
            upd_res = supabase.table("lesson_plans").update({
                "plan_json": cleaned_plan_json
            }).eq("id", plan_id).execute()

            if upd_res.data:
                cleaned_count += 1
                print(f"  ✅ Successfully cleaned and updated plan {plan_id} in Database!")

    print(f"\n=== DATABASE AUDIT SUMMARY ===")
    print(f" - Total lesson_plans audited: {len(plans)}")
    print(f" - Plans affected by double-escaped LaTeX: {affected_count}")
    print(f" - Plans successfully cleaned in DB: {cleaned_count}")

if __name__ == "__main__":
    audit_and_clean_lesson_plans()
