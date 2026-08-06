from app.db import supabase

def test_columns():
    sess = supabase.table("drona_sessions").select("*").limit(1).execute()
    print("drona_sessions columns:", list(sess.data[0].keys()) if sess.data else "Empty table")

    turns = supabase.table("drona_turns").select("*").limit(1).execute()
    print("drona_turns columns:", list(turns.data[0].keys()) if turns.data else "Empty table")

if __name__ == "__main__":
    test_columns()
