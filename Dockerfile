# Base image: Python 3.10 slim (lightweight aur fast)
FROM python:3.10-slim

# Container ke andar working directory set karna
WORKDIR /app

# System dependencies install karna (TgCrypto ko build karne ke liye gcc chahiye hota hai)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Bot ke main packages pre-install karna
# (Aapka code 'pyrogram' ko import karta hai, lekin pyrofork uska better fork hai 
# jo same import name use karta hai)
RUN pip install --no-cache-dir pyrofork tgcrypto

# Aapki script ko container mein copy karna
COPY bot.py .

# Bot start karne ka command
CMD ["python", "bot.py"]
