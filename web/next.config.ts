import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  // Settings has sub-pages; its old address (and GitHub's install return, with its query) opens
  // the first one.
  async redirects() {
    return [{ source: "/settings", destination: "/settings/integrations", permanent: false }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
