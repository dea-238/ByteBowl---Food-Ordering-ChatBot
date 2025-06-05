# ByteBowl---Food-Ordering-ChatBot

```markdown
# 🤖 ByteBowl — Smart Food Ordering Assistant

Fresh.AI is an intelligent food ordering web application powered by Dialogflow and FastAPI. Users can interact with a smart chatbot to place, modify, track, or cancel food orders, with full backend support and a real-time conversational UI.

---

## 🧠 Features

- 🎙️ Natural conversation using Dialogflow CX or ES
- 🍽️ Menu browsing, adding/removing items
- ✅ Order placement with unique ID
- 🚚 Real-time order tracking
- 💬 Smart contextual flow via Dialogflow contexts
- 🖥️ Responsive web UI with embedded chatbot
- ☁️ Easy deployment on Render

---

## 🛠️ Technologies

- **Frontend**: HTML5, CSS3, Google Fonts, Dialogflow Messenger
- **Backend**: FastAPI, Uvicorn
- **Database**: MySQL
- **NLP Engine**: Dialogflow (ES)
- **Deployment**: Render

---

## 🧪 Local Setup Instructions

### 1. Clone this repo

```bash
git clone https://github.com/yourusername/fresh-ai.git
cd NLP\ ChatBot
````

### 2. Set up MySQL Database

* Create database: `pandeyji_eatery`
* Import schema from `db/pandeyji_eatery.sql`
* Verify tables: `food_items`, `orders`, `order_tracking`

### 3. Setup Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate       # (Windows)
pip install -r requirements.txt
uvicorn main:app --reload
```

### 4. Setup Frontend

Open `frontend/index.html` in your browser (or host via Live Server)

---

## 🌐 Deployment on Render

### Prerequisites

* Push code to GitHub
* Ensure `start.sh` and `render.yaml` are in root

### Steps

1. Go to [https://render.com](https://render.com)
2. Click **New Web Service**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml`
5. App is live on `https://yourapp.onrender.com`

---

## 🔁 Dialogflow Setup

1. Go to [Dialogflow Console](https://dialogflow.cloud.google.com)
2. Create an agent (e.g., `FreshAI-Bot`)
3. Import intents and entities from `dialogflow_assets/`
4. Set webhook URL to: `https://your-backend.onrender.com/webhook`
5. Test via Dialogflow Console or embedded chatbot

---

## ✨ Sample Phrases

```
User: I want 2 pav bhaji and a mango lassi
Bot: So far you have: 2 pav bhaji, 1 mango lassi. Do you need anything else?

User: remove pav bhaji
Bot: Removed pav bhaji from your order!

User: that's it
Bot: ✅ Your order has been placed...
```

---

## 🖼️ Screenshots

* Chatbot ordering experience
* 3x3 visual menu
* Stylish landing page

---

## 🙌 Credits

* Inspired by Codebasics and Dialogflow tutorials
* Developed by \[Your Name]

---

## 📧 Contact

📮 Email: [info@aifoodbot.com](mailto:info@aifoodbot.com)
📍 Location: CMRIT Canteen, Bengaluru

---

```
