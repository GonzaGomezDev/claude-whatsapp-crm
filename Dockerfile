# Una sola imagen: el panel compilado y el agente que lo sirve.

FROM node:20-slim AS panel
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
# Editable a propósito: el agente encuentra skills/ y supabase/ relativos a la
# raíz del repo, no a site-packages.
COPY . .
RUN pip install --no-cache-dir -e .
COPY --from=panel /web/dist web/dist

# En un servidor, la Messages API con API key. El backend cli usa la suscripción
# de Claude Code, que es para uso individual (ver README, "Los dos backends").
ENV AGENT_BACKEND=messages_api
EXPOSE 8000
# Un solo proceso: breakers y rate limiters viven en memoria.
CMD ["uvicorn", "whatsapp_skills.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
