FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirement list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the files
COPY . .

# Run the bot
CMD ["python", "bot.py"]