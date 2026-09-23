FROM node:22-alpine AS build
WORKDIR /app
COPY packages/contracts ./packages/contracts
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
WORKDIR /app/apps/web
RUN npm ci
COPY apps/web ./
ENV VITE_API_BASE_URL=/api
RUN node --test src/infrastructure/httpV1Api.test.mjs && npm run build

FROM nginx:stable-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
