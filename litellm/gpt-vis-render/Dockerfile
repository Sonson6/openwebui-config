FROM node:20-bookworm-slim AS build
WORKDIR /app

# node-canvas (a dependency of @antv/gpt-vis-ssr) needs these to compile.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config python3 \
    libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY server.js ./

FROM node:20-bookworm-slim
WORKDIR /app

# Runtime libs for node-canvas (no -dev / compiler needed here).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libjpeg62-turbo libgif7 librsvg2-2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app /app

ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.js"]
