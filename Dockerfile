FROM python:3.12-slim-bookworm

# Set the working directory in the container to /app
WORKDIR /app
    
# Copy the current directory contents into the container at /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run my_script.py when the container launches
CMD ["python", "App.py"]