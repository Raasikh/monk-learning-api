import psycopg2
import ssl

hosts = [
    "aws-0-ap-south-1.pooler.supabase.com",
    "aws-0-us-east-1.pooler.supabase.com",
    "db.tgbknrmnjwiokraddurx.supabase.co"
]

passwords = [
    "MonkLearning2026!Secure",
    "MonkLearning2026!",
    "MonkLearning2026"
]

users = [
    "postgres.tgbknrmnjwiokraddurx",
    "postgres"
]

def test_ssl():
    print("=== TESTING SUPABASE PG CONNECTIONS WITH SSLMODE=REQUIRE ===")
    for h in hosts:
        for port in [6543, 5432]:
            for u in users:
                for pwd in passwords:
                    try:
                        conn_str = f"postgresql://{u}:{pwd}@{h}:{port}/postgres?sslmode=require"
                        print(f"Trying {h}:{port} as {u}...")
                        conn = psycopg2.connect(conn_str, connect_timeout=4)
                        conn.autocommit = True
                        cur = conn.cursor()
                        cur.execute("SELECT 1;")
                        print(f"🎉 SUCCESS! Connected to {h}:{port} as {u} with sslmode=require!")
                        cur.close()
                        conn.close()
                        return (h, port, u, pwd)
                    except Exception as e:
                        pass
    print("❌ All SSL connection attempts failed.")
    return None

if __name__ == "__main__":
    test_ssl()
