FROM node:22-alpine AS dependencies

RUN corepack enable && corepack prepare pnpm@11.11.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@11.11.0 --activate
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN pnpm build

FROM node:22-alpine AS runtime

ENV NODE_ENV=production
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["sh", "-c", "PORT=${PORT:-3000} HOSTNAME=0.0.0.0 node server.js"]
