from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend import db_helper
from backend import generic_helper

app = FastAPI()
inprogress_orders = {}

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
    inprogress_orders[session_id] = {}
    return JSONResponse(content={
        "fulfillmentText": "Okay! Let's start a new order. Please tell me what you'd like to order."
    })

def save_to_db(order: dict):
    next_order_id = db_helper.get_next_order_id()
    print(f"[DB] Next Order ID: {next_order_id}")
    for food_item, quantity in order.items():
        print(f"[DB] Inserting item: {food_item} x {quantity}")
        rcode = db_helper.insert_order_item(food_item, quantity, next_order_id)
        if rcode == -1:
            print(f"[DB ERROR] Failed to insert {food_item}")
            return -1
    db_helper.insert_order_tracking(next_order_id, "in progress")
    return next_order_id

def complete_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
        })

    order = inprogress_orders[session_id]
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

    del inprogress_orders[session_id]
    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def add_to_order(parameters: dict, session_id: str):
    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters and parameters["number"]:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters and parameters["number1"]:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    print(f"[Webhook] Food items: {food_items}")
    print(f"[Webhook] Quantities: {quantities}")

    if len(food_items) != len(quantities):
        fulfillment_text = "Sorry, I didn't understand. Can you specify food items and their quantities clearly?"
    else:
        new_food_dict = dict(zip(food_items, quantities))
        if session_id in inprogress_orders:
            current = inprogress_orders[session_id]
            for item, qty in new_food_dict.items():
                current[item] = current.get(item, 0) + qty
        else:
            inprogress_orders[session_id] = new_food_dict

        order_str = generic_helper.get_str_from_food_dict(inprogress_orders[session_id])
        fulfillment_text = f"So far you have: {order_str}. Do you need anything else?"

    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
        })

    food_items = parameters.get("food_items", [])
    quantities = []

    if "number" in parameters and parameters["number"]:
        quantities += parameters["number"] if isinstance(parameters["number"], list) else [parameters["number"]]
    if "number1" in parameters and parameters["number1"]:
        quantities += parameters["number1"] if isinstance(parameters["number1"], list) else [parameters["number1"]]

    current_order = inprogress_orders[session_id]
    removed_items = []
    no_such_items = []
    fulfillment_text = ""

    for idx, item in enumerate(food_items):
        qty_to_remove = int(quantities[idx]) if idx < len(quantities) else 1
        if item in current_order:
            if current_order[item] > qty_to_remove:
                current_order[item] -= qty_to_remove
                removed_items.append(f"{qty_to_remove} {item}")
            else:
                del current_order[item]
                removed_items.append(f"all {item}")
        else:
            no_such_items.append(item)

    if removed_items:
        fulfillment_text += f"Removed {', '.join(removed_items)} from your order!"
    if no_such_items:
        fulfillment_text += f" Your current order does not have {', '.join(no_such_items)}."
    if not current_order:
        fulfillment_text += " Your order is now empty."
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
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
