FROM node:20-alpine AS builder
WORKDIR /app
COPY webapp/frontend/package.json /app/package.json
RUN npm install
COPY webapp/frontend /app
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY webapp/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
