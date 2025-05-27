from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from backend import db_helper, generic_helper
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Thread pool for database operations
executor = ThreadPoolExecutor(max_workers=10)

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
        else:
            return JSONResponse(content={
                "fulfillmentText": f"Sorry, I don't know how to handle the intent '{intent}' yet."
            })
    except Exception as e:
        logger.error(f"Error handling request: {e}")
        return JSONResponse(content={
            "fulfillmentText": "Sorry, something went wrong. Please try again."
        })

async def new_order(parameters: dict, session_id: str):
    """Start a new order"""
    try:
        # Run database operation in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(executor, db_helper.clear_session_order, session_id)
        
        if success:
            return JSONResponse(content={
                "fulfillmentText": "Okay! Let's start a new order. Please tell me what you'd like to order."
            })
        else:
            return JSONResponse(content={
                "fulfillmentText": "Started a new order. Please tell me what you'd like to order."
            })
    except Exception as e:
        logger.error(f"Error starting new order: {e}")
        return JSONResponse(content={
            "fulfillmentText": "Started a new order. Please tell me what you'd like to order."
        })

async def complete_order(parameters: dict, session_id: str):
    """Complete the current order"""
    try:
        # Run database operations in thread pool
        loop = asyncio.get_event_loop()
        
        # Get session order
        order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        
        if not order:
            return JSONResponse(content={
                "fulfillmentText": "I'm having trouble finding your order. Can you start a new one?"
            })

        # Finalize order
        order_id, total = await loop.run_in_executor(
            executor, db_helper.finalize_order_and_get_total, session_id, order
        )
        
        if order_id is None:
            return JSONResponse(content={
                "fulfillmentText": "Sorry, something went wrong with your order. Please try again."
            })

        fulfillment_text = (
            f"✅ Your order has been placed!\n"
            f"🆔 Order ID: {order_id}\n"
            f"💰 Total: ₹{total:.2f}\n"
            "📦 Status: In Progress\n"
            "Please pay on delivery. Thanks!"
        )
        return JSONResponse(content={"fulfillmentText": fulfillment_text})

    except Exception as e:
        logger.error(f"Error completing order: {e}")
        return JSONResponse(content={
            "fulfillmentText": "Sorry, something went wrong with your order. Please try again."
        })

async def add_to_order(parameters: dict, session_id: str):
    """Add items to the order"""
    try:
        food_items = parameters.get("food_items", [])
        
        # Collect all quantity parameters efficiently
        quantities = []
        if "number" in parameters:
            number_list = parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
            quantities.extend(number_list)
        if "number1" in parameters:
            number1_list = parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]
            quantities.extend(number1_list)
        
        # Ensure we have quantities for all items
        while len(quantities) < len(food_items):
            quantities.append(1)  # Default to 1 if quantity missing
        
        # Prepare items dictionary for batch processing
        items_to_add = {}
        response_items = []
        
        for i, item in enumerate(food_items):
            try:
                qty = int(quantities[i]) if i < len(quantities) else 1
                items_to_add[item] = qty
                response_items.append(f"{qty} {item}")
            except (ValueError, TypeError):
                items_to_add[item] = 1
                response_items.append(f"1 {item}")

        # Return response immediately to avoid timeout
        response_text = f"Added {', '.join(response_items)} to your order!"
        
        # Process database operation asynchronously without waiting
        asyncio.create_task(process_order_batch(session_id, items_to_add))
        
        return JSONResponse(content={"fulfillmentText": response_text})

    except Exception as e:
        logger.error(f"Error adding to order: {e}")
        return JSONResponse(content={
            "fulfillmentText": "Sorry, I couldn't add those items. Please try again."
        })

async def remove_from_order(parameters: dict, session_id: str):
    """Remove items from the order"""
    try:
        food_items = parameters.get("food_items", [])
        
        # Extract quantities from all possible parameter fields
        quantities = []
        
        # Check for number parameters in the current request
        for param_name in ["number", "number1", "number2", "number3"]:
            if param_name in parameters:
                param_val = parameters[param_name]
                if isinstance(param_val, list):
                    quantities.extend(param_val)
                else:
                    quantities.append(param_val)
        
        # Also check the original parameters from context (sometimes quantities are in context)
        for param_name in ["number.original", "number1.original", "number2.original"]:
            if param_name in parameters:
                param_val = parameters[param_name]
                if isinstance(param_val, list):
                    quantities.extend([int(x) for x in param_val if str(x).isdigit()])
                elif str(param_val).isdigit():
                    quantities.append(int(param_val))

        # Fallback: Try to extract numbers from the query text if no quantities found
        if not quantities and 'queryText' in parameters:
            import re
            query_text = parameters.get('queryText', '')
            numbers = re.findall(r'\b(\d+)\b', query_text)
            quantities = [int(n) for n in numbers]

        # Log for debugging
        logger.info(f"Remove request - Items: {food_items}, Quantities: {quantities}, Session: {session_id}")
        logger.info(f"All parameters: {parameters}")

        # Run database operations in thread pool
        loop = asyncio.get_event_loop()
        
        # First, let's check what's actually in the session order
        current_order_before = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        logger.info(f"Current order before removal: {current_order_before}")
        
        removed, not_found = [], []
        for idx, item in enumerate(food_items):
            try:
                qty = int(quantities[idx]) if idx < len(quantities) else 1
            except (ValueError, TypeError, IndexError):
                qty = 1
                
            logger.info(f"Attempting to remove {qty} {item} from session {session_id}")
            
            result = await loop.run_in_executor(
                executor, db_helper.remove_from_session_order, session_id, item, qty
            )
            
            logger.info(f"Remove result for {item}: {result}")
            
            if result == "removed":
                removed.append(f"{qty} {item}")
            elif result == "all_removed":
                removed.append(f"all {item}")
            elif result == "not_found":
                not_found.append(item)
            elif result == "error":
                logger.error(f"Database error removing {item}")

        # Get current order status after removal
        current_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        logger.info(f"Current order after removal: {current_order}")
        
        msg = ""
        if removed:
            msg += f"Removed {', '.join(removed)}. "
        if not_found:
            msg += f"{', '.join(not_found)} were not found in your order. "
        if not current_order:
            msg += "Your order is now empty."
        else:
            order_str = generic_helper.get_str_from_food_dict(current_order)
            msg += f"Remaining items: {order_str}"
            
        return JSONResponse(content={"fulfillmentText": msg})
    
    except Exception as e:
        logger.error(f"Error removing from order: {e}")
        return JSONResponse(content={
            "fulfillmentText": "There was a problem removing items. Please try again."
        })

async def track_order(parameters: dict, session_id: str):
    """Track an order by ID"""
    try:
        order_id_param = parameters.get("order_id", 0)
        try:
            order_id = int(order_id_param)
        except (ValueError, TypeError):
            return JSONResponse(content={
                "fulfillmentText": "Please provide a valid Order ID to track."
            })
            
        if not order_id:
            return JSONResponse(content={
                "fulfillmentText": "Please provide a valid Order ID to track."
            })

        # Run database operation in thread pool
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(executor, db_helper.get_order_status, order_id)
        
        if status:
            return JSONResponse(content={
                "fulfillmentText": f"Order ID {order_id} is currently: {status}"
            })
        else:
            return JSONResponse(content={
                "fulfillmentText": f"No order found with ID {order_id}"
            })
    except Exception as e:
        logger.error(f"Error tracking order: {e}")
        return JSONResponse(content={
            "fulfillmentText": "Please provide a valid Order ID to track."
        })

async def process_order_batch(session_id: str, items_to_add: dict):
    """Process order items in background to avoid timeout"""
    try:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            executor, db_helper.update_session_order_batch, session_id, items_to_add
        )
        if success:
            logger.info(f"Successfully added items to session {session_id}: {items_to_add}")
        else:
            logger.error(f"Failed to add some items to session {session_id}: {items_to_add}")
    except Exception as e:
        logger.error(f"Error processing order batch for session {session_id}: {e}")

# Debug endpoint to check session orders
@app.get("/debug/session/{session_id}")
async def debug_session(session_id: str):
    """Debug endpoint to check what's in a session order"""
    try:
        loop = asyncio.get_event_loop()
        session_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        
        # Also get all available food items for reference
        with db_helper.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM food_items ORDER BY name")
            all_items = [row[0] for row in cursor.fetchall()]
            cursor.close()
        
        return {
            "session_id": session_id,
            "current_order": session_order,
            "available_items": all_items[:10],  # First 10 items for reference
            "total_available_items": len(all_items)
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return {"error": str(e)}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}