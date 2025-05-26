import mysql.connector

cnx = mysql.connector.connect(
    host="localhost",
    user="root",
    password="password",
    database="pandeyji_eatery"
)

def get_connection():
    return cnx

def get_next_order_id():
    cursor = cnx.cursor()
    cursor.execute("SELECT MAX(order_id) FROM orders")
    result = cursor.fetchone()[0]
    cursor.close()
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

def insert_order_tracking(order_id, status):
    cursor = cnx.cursor()
    cursor.execute("INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)", (order_id, status))
    cnx.commit()
    cursor.close()

def get_order_status(order_id):
    cursor = cnx.cursor()
    cursor.execute("SELECT status FROM order_tracking WHERE order_id = %s", (order_id,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else None

def get_total_order_price(order_id):
    cursor = cnx.cursor()
    cursor.execute("SELECT SUM(total_price) FROM orders WHERE order_id = %s", (order_id,))
    result = cursor.fetchone()[0]
    cursor.close()
    return result if result else 0

# --------- Persistent Session Storage ---------

def update_session_order(session_id, item, quantity):
    cursor = cnx.cursor()
    cursor.execute("SELECT quantity FROM session_orders WHERE session_id = %s AND item = %s", (session_id, item))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE session_orders SET quantity = quantity + %s WHERE session_id = %s AND item = %s", (quantity, session_id, item))
    else:
        cursor.execute("INSERT INTO session_orders (session_id, item, quantity) VALUES (%s, %s, %s)", (session_id, item, quantity))
    cnx.commit()
    cursor.close()

def get_session_order(session_id):
    cursor = cnx.cursor()
    cursor.execute("SELECT item, quantity FROM session_orders WHERE session_id = %s", (session_id,))
    rows = cursor.fetchall()
    cursor.close()
    return {item: quantity for item, quantity in rows}

def clear_session_order(session_id):
    cursor = cnx.cursor()
    cursor.execute("DELETE FROM session_orders WHERE session_id = %s", (session_id,))
    cnx.commit()
    cursor.close()

def remove_from_session_order(session_id, item, qty):
    cursor = cnx.cursor()
    cursor.execute("SELECT quantity FROM session_orders WHERE session_id = %s AND item = %s", (session_id, item))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        return "not_found"
    current_qty = result[0]
    if current_qty > qty:
        cursor.execute("UPDATE session_orders SET quantity = quantity - %s WHERE session_id = %s AND item = %s", (qty, session_id, item))
        cnx.commit()
        cursor.close()
        return "removed"
    else:
        cursor.execute("DELETE FROM session_orders WHERE session_id = %s AND item = %s", (session_id, item))
        cnx.commit()
        cursor.close()
        return "all_removed"
