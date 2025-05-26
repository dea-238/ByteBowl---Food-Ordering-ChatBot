from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend import db_helper, generic_helper
from fastapi.middleware.cors import CORSMiddleware
from fastapi.background import BackgroundTasks

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
async def handle_request(request: Request, background_tasks: BackgroundTasks):
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

    if intent in intent_handler_dict:
        return intent_handler_dict[intent](parameters, session_id, background_tasks)
    else:
        return JSONResponse(content={
            "fulfillmentText": f"Sorry, I don't know how to handle the intent '{intent}' yet."
        })
    

def new_order(parameters: dict, session_id: str):
    db_helper.clear_session_order(session_id)
    return JSONResponse(content={
        "fulfillmentText": "Okay! Let's start a new order. Please tell me what you'd like to order."
    })

def save_to_db(order: dict):
    order_id = db_helper.get_next_order_id()
    for item, qty in order.items():
        if db_helper.insert_order_item(item, qty, order_id) == -1:
            return -1
    db_helper.insert_order_tracking(order_id, "in progress")
    return order_id

def complete_order(parameters: dict, session_id: str):
    order = db_helper.get_session_order(session_id)
    if not order:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding your order. Can you start a new one?"
        })

    order_id = save_to_db(order)
    if order_id == -1:
        message = "Sorry, something went wrong with your order. Please try again."
    else:
        total = db_helper.get_total_order_price(order_id)
        message = (
            f"✅ Your order has been placed!\n"
            f"🆔 Order ID: {order_id}\n"
            f"💰 Total: ₹{total}\n"
            "📦 Status: In Progress\n"
            "Please pay on delivery. Thanks!"
        )
    db_helper.clear_session_order(session_id)
    return JSONResponse(content={"fulfillmentText": message})

def add_to_order(parameters: dict, session_id: str):
    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    if len(food_items) != len(quantities):
        return JSONResponse(content={"fulfillmentText": "Please specify both food items and their quantities."})

    for item, qty in zip(food_items, quantities):
        db_helper.update_session_order(session_id, item, int(qty))

    current_order = db_helper.get_session_order(session_id)
    order_str = generic_helper.get_str_from_food_dict(current_order)
    return JSONResponse(content={"fulfillmentText": f"So far, you have: {order_str}. Anything else?"})

def remove_from_order(parameters: dict, session_id: str):
    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    removed, not_found = [], []
    for idx, item in enumerate(food_items):
        qty = int(quantities[idx]) if idx < len(quantities) else 1
        result = db_helper.remove_from_session_order(session_id, item, qty)
        if result == "removed":
            removed.append(f"{qty} {item}")
        elif result == "all_removed":
            removed.append(f"all {item}")
        else:
            not_found.append(item)

    current_order = db_helper.get_session_order(session_id)
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

def track_order(parameters: dict, session_id: str):
    try:
        order_id = int(parameters.get("order_id", 0))
        if not order_id:
            raise ValueError("Missing order ID")
        status = db_helper.get_order_status(order_id)
        if status:
            return JSONResponse(content={"fulfillmentText": f"Order ID {order_id} is currently: {status}"})
        else:
            return JSONResponse(content={"fulfillmentText": f"No order found with ID {order_id}"})
    except Exception:
        return JSONResponse(content={"fulfillmentText": "Please provide a valid Order ID to track."})
