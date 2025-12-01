# src/utils/ai_client.py - FIXED VERSION
import os
import json
import boto3
import requests
import logging

logger = logging.getLogger(__name__)

# Global cache
_openai_key = None
_school_knowledge = None

def _get_openai_key():
    global _openai_key
    if _openai_key:
        return _openai_key

    # Try Secrets Manager first
    try:
        client = boto3.client("secretsmanager", region_name="us-east-2")
        secret = client.get_secret_value(SecretId="OPENAI_API_KEY")
        secret_string = secret["SecretString"]
        
        # FIX: Handle both JSON string and plain string
        try:
            data = json.loads(secret_string)
            _openai_key = data.get("OPENAI_API_KEY", secret_string)
        except json.JSONDecodeError:
            # If it's not JSON, use the string directly
            _openai_key = secret_string
            
        logger.info("✅ OpenAI key loaded from Secrets Manager")
        return _openai_key
    except Exception as e:
        logger.warning(f"Secrets Manager failed: {e}")

    # Fallback to env var
    _openai_key = os.getenv("OPENAI_API_KEY")
    if _openai_key:
        logger.info("✅ OpenAI key loaded from environment")
    else:
        logger.error("❌ No OpenAI key found!")
    return _openai_key

def _load_school_knowledge():
    """Load school knowledge from JSON file (cached)"""
    global _school_knowledge
    if _school_knowledge:
        return _school_knowledge
    
    try:
        # Try different file paths (depending on execution context)
        possible_paths = [
            "/var/task/src/data/school_knowledge.json",  # Lambda runtime path
            "src/data/school_knowledge.json",             # Relative path
            os.path.join(os.path.dirname(__file__), "../data/school_knowledge.json")  # Relative to this file
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    _school_knowledge = json.load(f)
                logger.info(f"✅ School knowledge loaded from {path}")
                return _school_knowledge
        
        logger.warning("⚠️ School knowledge file not found")
        return {}
    except Exception as e:
        logger.error(f"❌ Failed to load school knowledge: {e}")
        return {}

def generate_ai_response(user_message: str, context: str = None) -> str:
    api_key = _get_openai_key()
    if not api_key:
        return "I'm having a little trouble connecting right now. Please try again in a minute 😊"

    # Load school knowledge
    knowledge = _load_school_knowledge()

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Build system prompt with school knowledge
    system_prompt = (
        "You are Mya, a super friendly and professional assistant for Shining Smiles College "
        "in Harare, Zimbabwe. You speak naturally, use emojis, and sound like a real person. "
        "You're helpful, warm, and always excited to assist parents and students. "
        "Never say you're an AI. Keep replies short, clear, and conversational. "
        "Use Zimbabwean English (e.g., 'mom', 'school fees', 'gate pass', 'term').\n\n"
    )
    
    # Add school knowledge to the prompt
    if knowledge:
        system_prompt += "**IMPORTANT: Use ONLY the following verified school information when answering questions:**\n\n"
        
        # Add key information
        if "school_info" in knowledge:
            system_prompt += f"About: {knowledge['school_info']}\n\n"
        
        if "school_calendar" in knowledge:
            cal = knowledge["school_calendar"]
            system_prompt += f"📅 **Term 3 Dates**: Opens {cal.get('term_3_opening', 'TBD')}, Closes {cal.get('term_3_closing', 'TBD')}\n\n"
        
        if "contacts" in knowledge:
            contacts = knowledge["contacts"]
            system_prompt += f"📞 **Contacts**: {', '.join(contacts.get('phone', []))}\n"
            system_prompt += f"📧 **Email**: {contacts['emails'].get('general', '')}\n"
            system_prompt += f"💬 **WhatsApp**: {contacts.get('whatsapp', '')}\n\n"
        
        if "location" in knowledge:
            loc = knowledge["location"]
            system_prompt += "📍 **Locations**:\n"
            for key, value in loc.items():
                system_prompt += f"  - {value}\n"
            system_prompt += "\n"
        
        if "operating_times" in knowledge:
            times = knowledge["operating_times"]
            system_prompt += f"⏰ **School Hours**: {times.get('school_hours', 'TBD')}\n"
            system_prompt += f"Drop-off: {times.get('earliest_drop_off', 'TBD')} | Pick-up: {times.get('latest_pick_up', 'TBD')}\n\n"
        
        # Add FAQs reference
        if "faqs" in knowledge:
            system_prompt += "Use the FAQs in the knowledge base to answer common questions accurately.\n\n"
        
        system_prompt += "**CRITICAL**: When asked about school dates, locations, fees, or policies, ALWAYS use the exact information above. Never give generic or uncertain answers."

    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "assistant", "content": context})
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "max_tokens": 220,
        "temperature": 0.8,
        "top_p": 0.9
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info(f"🤖 AI Response: {reply}")
            return reply.replace('\"', '"').replace("\n\n", "\n")
        else:
            logger.error(f"❌ OpenAI error {resp.status_code}: {resp.text}")
            return "So sorry! I'm having a small hiccup. Try again or type *menu* 😊"
    except Exception as e:
        logger.error(f"❌ OpenAI request failed: {e}")
        return "I'm here to help! Reply *menu* for options 😊"