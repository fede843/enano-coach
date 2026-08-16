import { request as createHttpRequest, type IncomingMessage, type ServerResponse } from "node:http";
import { type Plugin } from "vite";
import { defineConfig } from "vitest/config";

import {
  filterRequestHeaders,
  filterResponseHeaders,
  generatedProxyErrorHeaders,
  isAllowlistedApiRoute,
  parseProxyTarget
} from "./scripts/proxy-policy.ts";

function bffProxyPlugin(): Plugin {
  const target = parseProxyTarget(process.env.BFF_PROXY_TARGET || "http://127.0.0.1:8000");

  return {
    name: "enano-coach-bff-proxy",
    configureServer(server) {
      server.middlewares.use((request: IncomingMessage, response: ServerResponse, next) => {
        const requestUrl = new URL(request.url || "/", "http://localhost");
        if (requestUrl.pathname !== "/api" && !requestUrl.pathname.startsWith("/api/")) {
          next();
          return;
        }

        if (!isAllowlistedApiRoute(request.method || "", requestUrl.pathname)) {
          response.writeHead(404, generatedProxyErrorHeaders());
          response.end(JSON.stringify({ error: "not found" }));
          return;
        }

        const upstreamUrl = new URL(target);
        upstreamUrl.pathname = requestUrl.pathname;
        upstreamUrl.search = requestUrl.search;
        const headers = {
          ...filterRequestHeaders(request.headers),
          host: upstreamUrl.host
        };
        const proxyRequest = createHttpRequest(
          upstreamUrl,
          { method: request.method, headers },
          (upstreamResponse) => {
            response.writeHead(
              upstreamResponse.statusCode || 502,
              filterResponseHeaders(upstreamResponse.headers)
            );
            upstreamResponse.pipe(response);
          }
        );
        proxyRequest.on("error", () => {
          if (!response.headersSent) {
            response.writeHead(502, generatedProxyErrorHeaders());
          }
          response.end(JSON.stringify({ error: "proxy unavailable" }));
        });
        request.pipe(proxyRequest);
      });
    }
  };
}

export default defineConfig({
  plugins: [bffProxyPlugin()],
  appType: "spa",
  server: {
    host: "127.0.0.1",
    port: 5173
  },
  build: {
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]"
      }
    }
  },
  test: {
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
    environment: "node"
  }
});
