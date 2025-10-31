import os, time, math
import psycopg

DB_URL = os.environ["DATABASE_URL"]
ALPHA = 0.15   # freq → weight curve
HALF_LIFE_DAYS = 45

def step():
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        # decay factor by last_seen age
        cur.execute("""
          UPDATE trajectory
          SET freq = GREATEST(0, round(freq * exp(- EXTRACT(EPOCH FROM (now()-last_seen))/(86400*%s))::numeric,0))
        """, (HALF_LIFE_DAYS,))
        # recompute weight from freq
        cur.execute("""UPDATE trajectory SET weight = 1 - exp(-%s * freq)""", (ALPHA,))
        conn.commit()

if __name__ == "__main__":
    while True:
        try:
            step()
        except Exception as e:
            print("worker error:", e)
        time.sleep(3600)
