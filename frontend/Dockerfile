FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS deps

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci


FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG INTERNAL_API_BASE=http://backend:8000/api
ARG NEXT_PUBLIC_API_BASE=/api

ENV NEXT_TELEMETRY_DISABLED=1
ENV INTERNAL_API_BASE=${INTERNAL_API_BASE}
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN npm run build


FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV INTERNAL_API_BASE=http://backend:8000/api
ENV NEXT_PUBLIC_API_BASE=/api

COPY --from=builder /app /app

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
