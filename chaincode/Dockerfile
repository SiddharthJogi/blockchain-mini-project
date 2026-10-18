FROM node:20-alpine

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install --omit=dev

COPY index.js ./
COPY lib/ ./lib/

ARG CC_SERVER_PORT=9999
ENV PORT=${CC_SERVER_PORT}
EXPOSE ${CC_SERVER_PORT}

CMD ["npm", "run", "start:server-nontls"]
