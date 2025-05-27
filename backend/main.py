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
        quantities = []

        # Collect all quantity parameters
        if "number" in parameters:
            quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
        if "number1" in parameters:
            quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

        if len(food_items) != len(quantities):
            return JSONResponse(content={
                "fulfillmentText": "Please specify both food items and their quantities."
            })

        # Prepare items dictionary for batch processing
        items_to_add = {}
        for item, qty in zip(food_items, quantities):
            try:
                items_to_add[item] = int(qty)
            except (ValueError, TypeError):
                items_to_add[item] = 1

        # Process all items in a single database transaction
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            executor, db_helper.update_session_order_batch, session_id, items_to_add
        )

        if success:
            response_text = f"Added {', '.join([f'{q} {i}' for i, q in zip(food_items, quantities)])} to your order!"
        else:
            response_text = "I added what I could to your order. Some items might not be available."

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
        quantities = []

        if "number" in parameters:
            quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
        if "number1" in parameters:
            quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

        # Run database operations in thread pool
        loop = asyncio.get_event_loop()
        
        removed, not_found = [], []
        for idx, item in enumerate(food_items):
            try:
                qty = int(quantities[idx]) if idx < len(quantities) else 1
            except (ValueError, TypeError):
                qty = 1
                
            result = await loop.run_in_executor(
                executor, db_helper.remove_from_session_order, session_id, item, qty
            )
            
            if result == "removed":
                removed.append(f"{qty} {item}")
            elif result == "all_removed":
                removed.append(f"all {item}")
            elif result == "not_found":
                not_found.append(item)

        # Get current order status
        current_order = await loop.run_in_executor(executor, db_helper.get_session_order, session_id)
        
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

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}