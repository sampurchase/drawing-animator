# Drawing Dance web app.  Build:  docker build -t drawing-dance .
# Run:    docker run -p 8080:8080 -v drawing-data:/data drawing-dance
FROM python:3.12-slim

# ffmpeg makes the videos (and reads music files). pillow-heif brings its own HEIC support.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Run as a normal user, not root. /data is where everything is saved.
RUN useradd --create-home --uid 1000 app \
    && mkdir /data && chown app:app /data

WORKDIR /app

# Libraries first, so rebuilding after a code change is quick.
# The headless OpenCV build has no screen libraries, which a server image doesn't have.
COPY requirements.txt requirements-web.txt ./
RUN sed 's/^opencv-python\b/opencv-python-headless/' requirements.txt > requirements-docker.txt \
    && sed 's#^-r requirements.txt#-r requirements-docker.txt#' requirements-web.txt > requirements-web-docker.txt \
    && pip install --no-cache-dir -r requirements-web-docker.txt

COPY animator ./animator
COPY webapp ./webapp
COPY animate.py ./

ENV DRAWINGS_DATA=/data \
    DRAWINGS_HOST=0.0.0.0 \
    DRAWINGS_PORT=8080 \
    PYTHONUNBUFFERED=1

USER app
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"

CMD ["python", "-m", "webapp"]
