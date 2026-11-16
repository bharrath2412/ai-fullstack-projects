# --- build -----------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

# Copy manifests first so the dependency layer is cached across source edits.
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --no-audit --no-fund || npm install --omit=dev --no-audit --no-fund

COPY index.html vite.config.js ./
COPY public ./public
COPY src ./src
COPY scripts ./scripts

RUN npm run build

# --- serve -----------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

# Run unprivileged: nginx on 8080, no root-owned paths at runtime.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
 && sed -i 's#^user .*##' /etc/nginx/nginx.conf || true

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1

USER nginx
CMD ["nginx", "-g", "daemon off;"]
