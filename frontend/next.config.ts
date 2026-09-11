import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // NOTE: no outputFileTracingRoot — it nests server.js under an extra
  // app/ directory in the standalone output, breaking the Docker runner
  // (which expects server.js at the standalone root).
  reactStrictMode: true,
  poweredByHeader: false,
  images: {
    formats: ["image/avif", "image/webp"],
  },
};

export default nextConfig;
