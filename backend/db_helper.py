import mysql.connector

# ✅ Recommended: Use a function to get a new connection each time
def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="password",  # change if needed
        database="pandeyji_eatery"
    )

def insert_order_item(food_item, quantity, order_id):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get item_id and price from food_items
        cursor.execute("SELECT item_id, price FROM food_items WHERE name = %s", (food_item,))
        result = cursor.fetchone()
        if result is None:
            print(f"[DB ERROR] No such item in food_items: {food_item}")
            return -1

        item_id, price = result
        total_price = float(price) * float(quantity)

        # Insert into orders
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
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def insert_order_tracking(order_id, status):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)",
            (order_id, status)
        )
        conn.commit()

    except Exception as e:
        print(f"[DB ERROR] {e}")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_total_order_price(order_id):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT SUM(total_price) FROM orders WHERE order_id = %s", (order_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return 0

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_next_order_id():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT MAX(order_id) FROM orders")
        result = cursor.fetchone()
        return 1 if result[0] is None else result[0] + 1

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return 1

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_order_status(order_id):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT status FROM order_tracking WHERE order_id = %s", (order_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return None

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ✅ For testing only
if __name__ == "__main__":
    print(get_next_order_id())
