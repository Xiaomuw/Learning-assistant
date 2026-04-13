FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --legacy-peer-deps


FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG INTERNAL_API_BASE=http://backend:8000/api
ARG NEXT_PUBLIC_API_BASE=/api

ENV NEXT_TELEMETRY_DISABLED=1
ENV INTERNAL_API_BASE=${INTERNAL_API_BASE}
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN npm run build


FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV INTERNAL_API_BASE=http://backend:8000/api
ENV NEXT_PUBLIC_API_BASE=/api

COPY --from=builder /app /app

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
