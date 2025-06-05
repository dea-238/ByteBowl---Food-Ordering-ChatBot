from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend import db_helper, generic_helper
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
import time

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=10)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "ByteBowl NLP backend is running!"}

@app.post("/webhook")
async def handle_request(request: Request):
    try:
        return await asyncio.wait_for(_handle_request_internal(request), timeout=4.5)
    except asyncio.TimeoutError:
        logger.warning("Webhook handler timed out")
        return JSONResponse(content={
            "fulfillmentText": "Sorry, the request took too long to process."
        })

async def _handle_request_internal(request: Request):
    payload = await request.json()
    intent = payload['queryResult']['intent']['displayName']
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult'].get('outputContexts', [])
    session_id = generic_helper.extract_session_id(output_contexts[0]["name"]) if output_contexts else "default"

    intent_handler_dict = {
        'new.order': new_order,
        'order.add': add_to_order,
        'order.add - context: ongoing-order': add_to_order,
        'order.remove': remove_from_order,
        'order.remove - context: ongoing-order': remove_from_order,
        'order.complete': complete_order,
        'order.complete - context: ongoing-order': complete_order,
        'track.order': track_order,
        'track.order - context: ongoing-tracking': track_order
    }

    handler = intent_handler_dict.get(intent)
    if handler:
        return await handler(parameters, session_id)
    return JSONResponse(content={"fulfillmentText": f"I can't handle the intent '{intent}' yet."})

# ---------- INTENT HANDLERS ----------

async def new_order(parameters: dict, session_id: str):
    try:
        loop = asyncio.get_event_loop()
        asyncio.create_task(loop.run_in_executor(executor, db_helper.clear_session_order, session_id))
        return JSONResponse(content={"fulfillmentText": "Okay! Let's start a new order. What would you like?"})
    except Exception as e:
        logger.error(f"Error starting new order: {e}")
        return JSONResponse(content={"fulfillmentText": "Failed to start a new order. Try again."})

async def add_to_order(parameters: dict, session_id: str):
    try:
        food_items = parameters.get("food_items", [])
        quantities = []

        for param in ["number", "number1"]:
            val = parameters.get(param)
            if isinstance(val, list):
                quantities.extend(val)
            elif val is not None:
                quantities.append(val)

        while len(quantities) < len(food_items):
            quantities.append(1)

        items_to_add = {}
        response_items = []

        for i, item in enumerate(food_items):
            try:
                qty = int(quantities[i])
            except (ValueError, IndexError):
                qty = 1
            items_to_add[item] = qty
            response_items.append(f"{qty} {item}")

        asyncio.create_task(process_order_batch(session_id, items_to_add))

        loop = asyncio.get_event_loop()
        session_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        order_summary = generic_helper.get_str_from_food_dict(session_order)

        return JSONResponse(content={
            "fulfillmentText": f"Added {', '.join(response_items)} to your order!\n🧾 Your current order: {order_summary}.\nWould you like to add anything else?"
        })

    except Exception as e:
        logger.error(f"Add error: {e}")
        return JSONResponse(content={"fulfillmentText": "Couldn't add items. Please try again."})

async def complete_order(parameters: dict, session_id: str):
    try:
        asyncio.create_task(finalize_order_async(session_id))
        return JSONResponse(content={"fulfillmentText": "Placing your order. You'll get a confirmation shortly!"})
    except Exception as e:
        logger.error(f"Error completing order: {e}")
        return JSONResponse(content={"fulfillmentText": "Order couldn't be placed. Try again."})

async def remove_from_order(parameters: dict, session_id: str):
    try:
        food_items = parameters.get("food_items", [])

        quantity = 1
        for key in ["number", "number1", "number2"]:
            val = parameters.get(key)
            if isinstance(val, list) and val:
                quantity = int(val[0])
                break
            elif isinstance(val, int):
                quantity = val
                break

        logger.info(f"Received remove request: {quantity} x {food_items} for session {session_id}")

        loop = asyncio.get_event_loop()
        before_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)

        removed, not_found = [], []
        for item in food_items:
            result = await loop.run_in_executor(executor, db_helper.remove_from_session_order, session_id, item, quantity)
            if result == "removed":
                removed.append(f"{quantity} {item}")
            elif result == "all_removed":
                removed.append(f"all {item}")
            elif result == "not_found":
                not_found.append(item)

        after_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        msg = ""
        if removed:
            msg += f"Removed {', '.join(removed)}. "
        if not_found:
            msg += f"{', '.join(not_found)} not found in your order. "
        if removed and not after_order:
            msg += "Your order is now empty."
        elif after_order:
            msg += f"Remaining items: {generic_helper.get_str_from_food_dict(after_order)}."

        return JSONResponse(content={"fulfillmentText": msg})

    except Exception as e:
        logger.error(f"Remove error: {e}")
        return JSONResponse(content={"fulfillmentText": "Couldn't remove the item. Please try again."})

async def track_order(parameters: dict, session_id: str):
    try:
        order_id = parameters.get("order_id", 0)
        try:
            order_id = int(order_id)
        except:
            return JSONResponse(content={"fulfillmentText": "Invalid order ID."})

        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(executor, db_helper.get_order_status, order_id)
        if status:
            return JSONResponse(content={"fulfillmentText": f"Order ID {order_id} is currently: {status}"})
        return JSONResponse(content={"fulfillmentText": "No order found with that ID."})
    except Exception as e:
        logger.error(f"Track error: {e}")
        return JSONResponse(content={"fulfillmentText": "Couldn't fetch status. Try again."})

# ---------- BACKGROUND TASKS ----------

async def process_order_batch(session_id: str, items_to_add: dict):
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, db_helper.update_session_order_batch, session_id, items_to_add)
    except Exception as e:
        logger.error(f"Order batch process failed: {e}")

async def finalize_order_async(session_id: str):
    try:
        loop = asyncio.get_event_loop()
        order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        if not order:
            logger.warning(f"No items found for session {session_id}")
            return
        order_id, total = await loop.run_in_executor(executor, db_helper.finalize_order_and_get_total, session_id, order)
        logger.info(f"✅ Order {order_id} placed for session {session_id} - ₹{total:.2f}")
    except Exception as e:
        logger.error(f"Finalize failed for session {session_id}: {e}")

async def remove_items_async(session_id: str, food_items: list, quantity: int):
    try:
        loop = asyncio.get_event_loop()
        for item in food_items:
            result = await loop.run_in_executor(
                executor, db_helper.remove_from_session_order, session_id, item, quantity
            )
            logger.info(f"Removed {quantity} {item}: result = {result}")
    except Exception as e:
        logger.error(f"Background remove failed for session {session_id}: {e}")

# ---------- Debug & Health ----------

@app.get("/debug/session/{session_id}")
async def debug_session(session_id: str):
    try:
        loop = asyncio.get_event_loop()
        session_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        with db_helper.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM food_items ORDER BY name")
            all_items = [row[0] for row in cursor.fetchall()]
            cursor.close()
        return {
            "session_id": session_id,
            "current_order": session_order,
            "available_items": all_items[:10],
            "total_available_items": len(all_items)
        }
    except Exception as e:
        logger.error(f"Debug endpoint failed: {e}")
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}
