import mysql.connector
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
from contextlib import contextmanager
import logging

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@contextmanager
def get_connection():
    """Context manager for database connections to ensure proper cleanup"""
    conn = None
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise Exception("DATABASE_URL not set in environment variables")

        if db_url.startswith("mysql://"):
            db_url = db_url.replace("mysql://", "")

        parsed = urlparse(f"//{db_url}", scheme="mysql")
        conn = mysql.connector.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip('/'),
            autocommit=False,  # Explicit transaction control
            connection_timeout=10,  # 10 second timeout
            pool_name='mypool',
            pool_size=5,
            pool_reset_session=True
        )
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()

# ---------- Order Management ----------

def get_next_order_id():
    """Get the next available order ID"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(order_id) FROM orders")
            result = cursor.fetchone()[0]
            cursor.close()
            return 1 if result is None else result + 1
    except Exception as e:
        logger.error(f"Error getting next order ID: {e}")
        raise

def insert_order_item(food_item, quantity, order_id):
    """Insert a single order item - deprecated, use batch insert instead"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item_id, price FROM food_items WHERE name = %s", (food_item,))
            result = cursor.fetchone()
            if result is None:
                cursor.close()
                return -1
            
            item_id, price = result
            total_price = float(price) * int(quantity)
            cursor.execute("""
                INSERT INTO orders (order_id, item_id, quantity, total_price)
                VALUES (%s, %s, %s, %s)
            """, (order_id, item_id, quantity, total_price))
            conn.commit()
            cursor.close()
            return 0
    except Exception as e:
        logger.error(f"Error inserting order item: {e}")
        return -1

def insert_order_tracking(order_id, status):
    """Insert order tracking status"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)", (order_id, status))
            conn.commit()
            cursor.close()
    except Exception as e:
        logger.error(f"Error inserting order tracking: {e}")
        raise

def get_order_status(order_id):
    """Get the status of an order"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM order_tracking WHERE order_id = %s", (order_id,))
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting order status: {e}")
        return None

def get_total_order_price(order_id):
    """Get the total price of an order"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(total_price) FROM orders WHERE order_id = %s", (order_id,))
            result = cursor.fetchone()[0]
            cursor.close()
            return result if result else 0
    except Exception as e:
        logger.error(f"Error getting order total: {e}")
        return 0

# ---------- Session Order Management ----------

def update_session_order_batch(session_id, items_dict):
    """Update session order with multiple items in a single transaction - optimized"""
    if not items_dict:
        return True
        
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all item IDs in one query with better error handling
            item_names = list(items_dict.keys())
            placeholders = ','.join(['%s'] * len(item_names))
            cursor.execute(f"SELECT name, item_id FROM food_items WHERE name IN ({placeholders})", item_names)
            name_to_id = {name: item_id for name, item_id in cursor.fetchall()}
            
            # Skip items not found in database
            valid_items = {name: qty for name, qty in items_dict.items() if name in name_to_id}
            if not valid_items:
                cursor.close()
                logger.warning("No valid items found in database")
                return False
            
            # Use INSERT ... ON DUPLICATE KEY UPDATE for better performance
            item_ids = [name_to_id[name] for name in valid_items.keys()]
            quantities = list(valid_items.values())
            
            # Prepare data for upsert
            upsert_data = [(session_id, name_to_id[name], qty) for name, qty in valid_items.items()]
            
            # Use MySQL's INSERT ... ON DUPLICATE KEY UPDATE for atomic upsert
            cursor.executemany("""
                INSERT INTO session_orders (session_id, item_id, quantity) 
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
            """, upsert_data)
            
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        logger.error(f"Error updating session order batch: {e}")
        return False

def update_session_order(session_id, item, quantity):
    """Update session order for a single item"""
    return update_session_order_batch(session_id, {item: quantity})

def get_session_order(session_id):
    """Get the current session order"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.name, s.quantity 
                FROM session_orders s
                JOIN food_items f ON s.item_id = f.item_id
                WHERE s.session_id = %s
            """, (session_id,))
            rows = cursor.fetchall()
            cursor.close()
            return {item: quantity for item, quantity in rows}
    except Exception as e:
        logger.error(f"Error getting session order: {e}")
        return {}

def clear_session_order(session_id):
    """Clear the session order"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM session_orders WHERE session_id = %s", (session_id,))
            conn.commit()
            cursor.close()
            return True
    except Exception as e:
        logger.error(f"Error clearing session order: {e}")
        return False

def remove_from_session_order(session_id, item, qty):
    """Remove items from session order with improved error handling and logging"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            logger.info(f"Removing {qty} {item} from session {session_id}")
            
            # Get item_id and current quantity in one transaction with better matching
            # Try exact match first, then partial match
            cursor.execute("""
                SELECT f.item_id, f.name, COALESCE(s.quantity, 0) as current_qty
                FROM food_items f
                LEFT JOIN session_orders s ON f.item_id = s.item_id AND s.session_id = %s
                WHERE f.name = %s
                LIMIT 1
            """, (session_id, item))
            
            result = cursor.fetchone()
            
            # If exact match not found, try partial match (case insensitive)
            if not result:
                cursor.execute("""
                    SELECT f.item_id, f.name, COALESCE(s.quantity, 0) as current_qty
                    FROM food_items f
                    LEFT JOIN session_orders s ON f.item_id = s.item_id AND s.session_id = %s
                    WHERE LOWER(f.name) LIKE LOWER(%s) OR LOWER(%s) LIKE LOWER(CONCAT('%', f.name, '%'))
                    LIMIT 1
                """, (session_id, f"%{item}%", item))
                result = cursor.fetchone()
            
            if not result:
                logger.warning(f"Item '{item}' not found in food_items table")
                cursor.close()
                return "not_found"
            
            item_id, actual_name, current_qty = result
            logger.info(f"Found item: {actual_name} (ID: {item_id}) with current quantity: {current_qty}")
            
            if current_qty == 0:
                logger.info(f"Item {actual_name} not in session order")
                cursor.close()
                return "not_found"
            
            if current_qty > qty:
                cursor.execute("""
                    UPDATE session_orders SET quantity = quantity - %s 
                    WHERE session_id = %s AND item_id = %s
                """, (qty, session_id, item_id))
                conn.commit()
                logger.info(f"Reduced {actual_name} quantity by {qty}")
                cursor.close()
                return "removed"
            else:
                cursor.execute("""
                    DELETE FROM session_orders 
                    WHERE session_id = %s AND item_id = %s
                """, (session_id, item_id))
                conn.commit()
                logger.info(f"Removed all {actual_name} from order")
                cursor.close()
                return "all_removed"
    except Exception as e:
        logger.error(f"Error removing from session order: {e}")
        return "error"

def finalize_order_and_get_total(session_id, order_dict):
    """Finalize the order and return order_id and total - all in one transaction"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Get next order ID
            cursor.execute("SELECT MAX(order_id) FROM orders")
            result = cursor.fetchone()[0]
            order_id = 1 if result is None else result + 1
            
            # Get all item details in one query
            item_names = list(order_dict.keys())
            if not item_names:
                cursor.close()
                return None, 0
                
            placeholders = ','.join(['%s'] * len(item_names))
            cursor.execute(f"SELECT name, item_id, price FROM food_items WHERE name IN ({placeholders})", item_names)
            item_details = {name: (item_id, price) for name, item_id, price in cursor.fetchall()}
            
            # Prepare batch insert data
            order_items = []
            total = 0
            
            for item_name, qty in order_dict.items():
                if item_name not in item_details:
                    continue
                
                item_id, price = item_details[item_name]
                line_total = float(price) * int(qty)
                total += line_total
                order_items.append((order_id, item_id, qty, line_total))
            
            if not order_items:
                cursor.close()
                return None, 0
            
            # Insert all order items in batch
            cursor.executemany("""
                INSERT INTO orders (order_id, item_id, quantity, total_price)
                VALUES (%s, %s, %s, %s)
            """, order_items)
            
            # Insert order tracking
            cursor.execute("INSERT INTO order_tracking (order_id, status) VALUES (%s, %s)", (order_id, "in progress"))
            
            # Clear session order
            cursor.execute("DELETE FROM session_orders WHERE session_id = %s", (session_id,))
            
            conn.commit()
            cursor.close()
            return order_id, total
    except Exception as e:
        logger.error(f"Error finalizing order: {e}")
        return None, 0