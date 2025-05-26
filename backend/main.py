from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend import db_helper
from backend import generic_helper
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or specify Dialogflow's domain if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "ByteBowl NLP backend is running!"}

@app.post("/webhook")
async def handle_request(request: Request):
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
        return intent_handler_dict[intent](parameters, session_id)
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
    next_order_id = db_helper.get_next_order_id()
    for food_item, quantity in order.items():
        rcode = db_helper.insert_order_item(food_item, quantity, next_order_id)
        if rcode == -1:
            return -1
    db_helper.insert_order_tracking(next_order_id, "in progress")
    return next_order_id

def complete_order(parameters: dict, session_id: str):
    order = db_helper.get_session_order(session_id)
    if not order:
        return JSONResponse(content={
            "fulfillmentText": "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
        })

    order_id = save_to_db(order)
    if order_id == -1:
        fulfillment_text = "Sorry, I couldn't process your order due to a backend error. Please try again."
    else:
        order_total = db_helper.get_total_order_price(order_id)
        fulfillment_text = (
            f"✅ Your order has been placed successfully!\n"
            f"🆔 Order ID: {order_id}\n"
            f"💰 Total: ₹{order_total}\n"
            "📦 Status: In Progress\n"
            "Please pay at the time of delivery. Thank you!"
        )
    db_helper.clear_session_order(session_id)
    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def add_to_order(parameters: dict, session_id: str):
    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    if len(food_items) != len(quantities):
        return JSONResponse(content={
            "fulfillmentText": "Sorry, I didn't understand. Can you specify food items and their quantities clearly?"
        })

    for item, qty in zip(food_items, quantities):
        db_helper.update_session_order(session_id, item, int(qty))

    order = db_helper.get_session_order(session_id)
    order_str = generic_helper.get_str_from_food_dict(order)
    return JSONResponse(content={"fulfillmentText": f"So far you have: {order_str}. Do you need anything else?"})

def remove_from_order(parameters: dict, session_id: str):
    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    removed_items, no_such_items = [], []
    for idx, item in enumerate(food_items):
        qty = int(quantities[idx]) if idx < len(quantities) else 1
        result = db_helper.remove_from_session_order(session_id, item, qty)
        if result == "removed":
            removed_items.append(f"{qty} {item}")
        elif result == "all_removed":
            removed_items.append(f"all {item}")
        else:
            no_such_items.append(item)

    order = db_helper.get_session_order(session_id)
    fulfillment_text = ""
    if removed_items:
        fulfillment_text += f"Removed {', '.join(removed_items)} from your order!"
    if no_such_items:
        fulfillment_text += f" Your current order does not have {', '.join(no_such_items)}."
    if not order:
        fulfillment_text += " Your order is now empty."
    else:
        order_str = generic_helper.get_str_from_food_dict(order)
        fulfillment_text += f" Here is what is left in your order: {order_str}"

    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def track_order(parameters: dict, session_id: str):
    try:
        order_id = int(parameters.get('order_id', 0))
        if not order_id:
            raise ValueError("Missing order ID")
        order_status = db_helper.get_order_status(order_id)
        if order_status:
            fulfillment_text = f"The order status for order id: {order_id} is: {order_status}"
        else:
            fulfillment_text = f"No order found with order id: {order_id}"
    except Exception:
        fulfillment_text = "Invalid or missing order ID. Please try again."

    return JSONResponse(content={"fulfillmentText": fulfillment_text})
