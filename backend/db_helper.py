import mysql.connector
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL not set in environment variables")

    if db_url.startswith("mysql://"):
        db_url = db_url.replace("mysql://", "")

    parsed = urlparse(f"//{db_url}", scheme="mysql")
    return mysql.connector.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/')
    )

# ---------- Order Management ----------

def get_next_order_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(order_id) FROM orders")
    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return 1 if result is None else result + 1

def insert_order_item(food_item, quantity, order_id):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_id, price FROM food_items WHERE name = %s", (food_item,))
        result = cursor.fetchone()
        if result is None:
            return -1
        item_id, price = result
        total_price = float(price) * int(quantity)
        cursor.execute("""
            INSERT INTO orders (order_id, item_id, quantity, total_price)
            VALUES (%s, %s, %s, %s)
        """, (order_id, item_id, quantity, total_price))
        conn.commit()
        return 0
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return -1
    finally:
        cursor.close()
        conn.close()

def insert_order_tracking(order_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)", (order_id, status))
    conn.commit()
    cursor.close()
    conn.close()

def get_order_status(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM order_tracking WHERE order_id = %s", (order_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

def get_total_order_price(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(total_price) FROM orders WHERE order_id = %s", (order_id,))
    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return result if result else 0

# ---------- Session Order Management ----------

def update_session_order(session_id, item, quantity):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT item_id FROM food_items WHERE name = %s", (item,))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return
    item_id = result[0]

    cursor.execute("SELECT quantity FROM session_orders WHERE session_id = %s AND item_id = %s", (session_id, item_id))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE session_orders SET quantity = quantity + %s WHERE session_id = %s AND item_id = %s", (quantity, session_id, item_id))
    else:
        cursor.execute("INSERT INTO session_orders (session_id, item_id, quantity) VALUES (%s, %s, %s)", (session_id, item_id, quantity))
    conn.commit()
    cursor.close()
    conn.close()

def get_session_order(session_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.name, s.quantity 
        FROM session_orders s
        JOIN food_items f ON s.item_id = f.item_id
        WHERE s.session_id = %s
    """, (session_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {item: quantity for item, quantity in rows}

def clear_session_order(session_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM session_orders WHERE session_id = %s", (session_id,))
    conn.commit()
    cursor.close()
    conn.close()

def remove_from_session_order(session_id, item, qty):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT item_id FROM food_items WHERE name = %s", (item,))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return "not_found"
    item_id = result[0]

    cursor.execute("SELECT quantity FROM session_orders WHERE session_id = %s AND item_id = %s", (session_id, item_id))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return "not_found"

    current_qty = result[0]
    if current_qty > qty:
        cursor.execute("UPDATE session_orders SET quantity = quantity - %s WHERE session_id = %s AND item_id = %s", (qty, session_id, item_id))
        conn.commit()
        cursor.close()
        conn.close()
        return "removed"
    else:
        cursor.execute("DELETE FROM session_orders WHERE session_id = %s AND item_id = %s", (session_id, item_id))
        conn.commit()
        cursor.close()
        conn.close()
        return "all_removed"
def finalize_order_and_get_total(session_id, order_dict):
    conn = get_connection()
    cursor = conn.cursor()

    order_id = get_next_order_id()

    total = 0
    for item_name, qty in order_dict.items():
        cursor.execute("SELECT item_id, price FROM food_items WHERE name = %s", (item_name,))
        row = cursor.fetchone()
        if not row:
            continue  # Skip invalid items

        item_id, price = row
        line_total = price * qty
        total += line_total

        cursor.execute("""
            INSERT INTO orders (order_id, item_id, quantity, total_price)
            VALUES (%s, %s, %s, %s)
        """, (order_id, item_id, qty, line_total))

    cursor.execute("INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)", (order_id, "in progress"))
    cursor.execute("DELETE FROM session_orders WHERE session_id = %s", (session_id,))

    conn.commit()
    cursor.close()
    conn.close()
    return order_id, total
