# ---- Build stage ----
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first (cached layer)
COPY package.json package-lock.json ./
RUN npm install

# Copy source and build the production bundle
COPY . .
RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine

# Copy the built static files to nginx's web root
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom nginx config (handles React Router)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]