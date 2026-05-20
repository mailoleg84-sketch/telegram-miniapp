import sqlite3

conn = sqlite3.connect("bot.db")
cur = conn.cursor()

def get_user(user_id):
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()

    if not user:
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return {"level": "A1", "xp": 0}

    return {"level": user[1], "xp": user[2]}


def add_xp(user_id, amount=10):
    cur.execute("UPDATE users SET xp = xp + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
