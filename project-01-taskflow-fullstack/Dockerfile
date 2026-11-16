# ---- API ----
FROM node:20-alpine AS api
WORKDIR /app
RUN apk add --no-cache python3 make g++
COPY server/package*.json ./
RUN npm ci --omit=dev
COPY server/ ./
ENV NODE_ENV=production PORT=4000 DB_PATH=/data/taskflow.db
VOLUME ["/data"]
EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:4000/api/health || exit 1
CMD ["node", "src/index.js"]

# ---- web (built assets served by nginx) ----
FROM node:20-alpine AS web-build
WORKDIR /web
COPY client/package*.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM nginx:1.27-alpine AS web
COPY --from=web-build /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
