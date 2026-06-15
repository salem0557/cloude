# Apify's Python actor base image (Debian + Python).
FROM apify/actor-python:3.11

# Install dependencies first so Docker can cache this layer.
COPY requirements.txt ./
RUN echo "Python version:" \
 && python --version \
 && echo "Installing dependencies:" \
 && pip install --no-cache-dir -r requirements.txt \
 && echo "All installed Python packages:" \
 && pip freeze

# Copy the rest of the source.
COPY . ./

# Run the actor as a module: src/__main__.py.
CMD ["python3", "-m", "src"]
