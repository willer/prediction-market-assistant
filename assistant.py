import traceback
import streamlit as st
import requests, time, json, os
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()
perplexity_api_key = os.environ['PERPLEXITY_API_KEY']

st.header("Prediction Market Assistant")

@st.cache_data(persist="disk")
def load_data():
    """Fetch market data with disk persistence"""
    page_size, page, all_events = 200, 0, []

    r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?limit={page_size}&with_nested_markets=true")
    response = r.json()
    all_events.extend(response['events'])

    while response['cursor'] != '':
        r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?cursor={response['cursor']}&limit=200&with_nested_markets=true")
        response = r.json()
        all_events.extend(response['events'])     

    return all_events

with st.spinner('Loading events...'):
    events = load_data()
st.write(f"Loaded {len(events)} events")

search = st.text_input("Search Events")

# Build categories with "-- All" option
categories = {"-- All": events}
for event in events:
    category = event['category']
    if category not in categories:
        categories[category] = []
    categories[category].append(event)

category_selectbox = st.selectbox("Categories", ["-- All"] + sorted(k for k in categories.keys() if k != "-- All"))

@st.dialog("Analysis")
def display_analysis(analysis):
    st.write(analysis)

def evaluate_bet(**data):    
    class Contract(BaseModel):
        ticker: str
        side: str
        bid_price: int
        reason: str
        confidence: int

    ticker = data.get('ticker')
    context = data.get('context')
    market = data.get('market')
    
    headers = {"Authorization": f"Bearer {perplexity_api_key}"}
    payload = {
        "model": "sonar-reasoning-pro",
        "messages": [{
                "role": "system", 
                "content": "You are a prediction market assistant. First think through your analysis in a <think> tag, then provide your final decision as a JSON object with these fields: side (yes/no), ticker (string), bid_price (integer), reason (string), confidence (integer 0-100)."
            },
            {"role": "user", "content": context},
        ],
        "response_format": {
            "type": "json_schema", 
            "json_schema": {"schema": Contract.model_json_schema()}
        },
    }

    response = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload).json()
    content = response["choices"][0]["message"]["content"]
    thinking = ""
    json_str = ""
    
    try:
        # Split thinking and JSON parts
        parts = content.split("</think>")
        if len(parts) > 1:
            thinking = parts[0].replace("<think>", "").strip()
            json_str = parts[1].strip().replace("```json", "").replace("```", "").strip()
        else:
            thinking = ""
            json_str = content

        contract = json.loads(json_str)
        
        # Display the analysis with thinking process
        if thinking:
            st.markdown("*Thinking process:*")
            st.markdown(f"*{thinking}*")
            st.markdown("---")

        # Only give 'buy' if AI is confident and suggested buy price is > current price + 3
        ai_side = contract['side']
        ai_price = contract['bid_price']
        market_price = market[f"{ai_side}_bid"]
        if contract['side'] == 'yes' and contract['confidence'] > 80 and ai_price > market_price + 3:
            st.markdown(f"**Final Analysis:** BUY {contract['ticker']} '{ai_side}', market price at {market_price}, AI prices at {ai_price}.")
        else:
            st.markdown(f"**Final Analysis:** SKIP {contract['ticker']} '{ai_side}', market price at {market_price}, AI prices at {ai_price}.")
        st.markdown(f"**Reasoning:** {contract['reason']}")
        st.markdown(f"**Confidence:** {contract['confidence']}%")
        
    except Exception as e:
        st.error(f"Failed to parse response: {str(e)}, traceback: {traceback.format_exc()}\nResponse was: {content}\n\nThinking was: {thinking}\nJSON was: {json_str}")

if search:  # Only show results if there's a search term
    search_terms = search.lower().split()
    events_to_search = categories[category_selectbox]
    
    for event in events_to_search:
        # Check if all search terms are in the title
        title_lower = event['title'].lower()
        if all(term in title_lower for term in search_terms):
            st.divider()
            bet_markdown = f"#### {event['title']}\n"
            if 'markets' in event:
                for market in event['markets']:
                    bet_markdown += f"##### {market['yes_sub_title']} - {market['ticker']}\n"
                    bet_markdown += f"Yes: {market['yes_bid']}-{market['yes_ask']}\n"
                    bet_markdown += f"No: {market['no_bid']}-{market['no_ask']}\n"

                st.markdown(bet_markdown)
                st.button("Evaluate Bet", 
                          key=event['event_ticker'], 
                          on_click=evaluate_bet, 
                          kwargs={"ticker": event['event_ticker'], 
                                  "context": bet_markdown, 
                                  "market": market})