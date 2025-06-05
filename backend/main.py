from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
import random
import time
from backend import db_helper, generic_helper

# Logger setup
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

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    intent = payload["queryResult"]["intent"]["displayName"]
    parameters = payload["queryResult"]["parameters"]
    output_contexts = payload["queryResult"].get("outputContexts", [])
    session_id = generic_helper.extract_session_id(output_contexts[0]["name"]) if output_contexts else "default"

    handler = intent_router.get(intent)
    if handler:
        return await handler(parameters, session_id)
    return JSONResponse(content={"fulfillmentText": f"Sorry, I can't handle the intent '{intent}' yet."})

@app.get("/dialogflow/default_welcome")
async def default_welcome():
    messages = [
        "Hello, How can I help you? You can say 'New Order' or 'Track Order'",
        "Good day! What can I do for you today? You can say 'New Order' or 'Track Order'",
        "Greetings! How can I assist? You can say 'New Order' or 'Track Order'"
    ]
    return {"fulfillmentText": random.choice(messages)}

@app.get("/dialogflow/default_fallback")
async def default_fallback():
    msg = (
        "I didn't understand. You can say 'New Order' or 'Track Order'. "
        "Also, in a new order, please mention only items from our available menu: "
        "Pav Bhaji, Chole Bhature, Pizza, Mango Lassi, Masala Dosa, Biryani, Vada Pav, Rava Dosa, and Samosa. "
        "Also specify a quantity for each item for example: 'One pizza and 2 chole bhature'."
    )
    return {"fulfillmentText": msg}

# Intent handlers (partial shown)
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
        elif not removed and not not_found:
            msg += "No changes made to your order."

        return JSONResponse(content={"fulfillmentText": msg.strip()})
    except Exception as e:
        logger.error(f"Remove error: {e}")
        return JSONResponse(content={"fulfillmentText": "Couldn't remove the item. Please try again."})

# Intent router
intent_router = {
    "order.remove": remove_from_order,
    "order.remove - context: ongoing-order": remove_from_order,
}
