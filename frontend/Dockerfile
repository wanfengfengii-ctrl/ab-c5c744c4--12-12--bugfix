# Build the React/Vite workbench, then serve it with nginx which also
# reverse-proxies /api to the FastAPI service.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# Use a cache directory inside the writable build context.
RUN npm ci --cache /tmp/npm-cache || npm install --cache /tmp/npm-cache
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/workbench.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
