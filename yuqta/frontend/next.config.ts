import type { NextConfig } from "next";

// Keep in step with the backend's MAX_AUDIO_MB (default 200), plus multipart overhead.
const UPLOAD_LIMIT = "205mb";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (see frontend/Dockerfile).
  output: "standalone",
  experimental: {
    // Server Actions default to a 1MB body; audio uploads need more.
    serverActions: { bodySizeLimit: UPLOAD_LIMIT },
    // proxy.ts buffers request bodies and truncates past 10MB by default, which would corrupt uploads.
    proxyClientMaxBodySize: UPLOAD_LIMIT,
  },
};

export default nextConfig;
