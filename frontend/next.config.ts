import type { NextConfig } from "next";

// In Docker, nginx routes /api and /ws to the backend before requests reach Next.js.
// For `npm run dev` without nginx, these rewrites proxy /api to the local backend.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/health", destination: `${backend}/health` },
    ];
  },
};

export default nextConfig;
